"""On-demand cloud GPU worker (EC2 g6.xlarge, one NVIDIA L4) for the online demo. Idempotent.

  python scripts/aws_gpu.py up       # create the worker (needs G-instance vCPU quota >= 4),
                                     # then register it with the API so uploads wake it
  python scripts/aws_gpu.py status   # instance state + quota

The worker shares the Neon database and S3 bucket with the API and PACE. On boot it installs the
backend (+ ml/ for the model code) from GitHub, downloads the checkpoint from
s3://<bucket>/<prefix>models/E-07c-seed2/, runs `python -m app.worker`, and stops the machine
after IDLE_SHUTDOWN_SEC (900 s) without work. Stopped, it costs only its disk; the API starts it
again when a job is queued and no worker (PACE or cloud) is online.
"""

import json
import sys
import time
from pathlib import Path

from aws_api import NAME as API_NAME
from aws_api import REGION, REPO, elastic_ip, env_file, key_pair, session, ssh_cmd, tag
from botocore.exceptions import ClientError

NAME = "streamsense-gpu"
MODEL_PREFIX = "models/E-07c-seed2/"
QUOTA = ("ec2", "L-DB2E81BA")  # Running On-Demand G and VT instances (vCPU)


def role(iam, bucket: str, prefix: str) -> str:  # noqa: ANN001
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
             "Action": "sts:AssumeRole"}]}  # fmt: skip
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
         "Resource": f"arn:aws:s3:::{bucket}/{prefix}*"},
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"], "Resource": f"arn:aws:s3:::{bucket}"},
    ]}  # fmt: skip
    try:
        iam.get_role(RoleName=NAME)
    except ClientError:
        iam.create_role(RoleName=NAME, AssumeRolePolicyDocument=json.dumps(trust), Tags=tag(NAME))
    iam.put_role_policy(RoleName=NAME, PolicyName=NAME, PolicyDocument=json.dumps(policy))
    try:
        iam.get_instance_profile(InstanceProfileName=NAME)
    except ClientError:
        iam.create_instance_profile(InstanceProfileName=NAME)
        iam.add_role_to_instance_profile(InstanceProfileName=NAME, RoleName=NAME)
        time.sleep(10)
    return NAME


def security_group(ec2) -> str:  # noqa: ANN001  (SSH only; the worker makes outbound calls)
    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [NAME]}])[
        "SecurityGroups"
    ]
    if found:
        return found[0]["GroupId"]
    sg = ec2.create_security_group(
        GroupName=NAME, Description="StreamSense GPU worker: SSH", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])  # fmt: skip
    return sg


def user_data(env: dict[str, str], bucket: str, prefix: str) -> str:
    lines = "\n".join(f"{k}={v}" for k, v in env.items())
    return f"""#!/bin/bash
set -euxo pipefail
id streamsense || useradd -r -m -d /opt/streamsense -s /bin/bash streamsense
echo 'streamsense ALL=(root) NOPASSWD: /usr/sbin/shutdown' > /etc/sudoers.d/streamsense && chmod 440 /etc/sudoers.d/streamsense
sudo -iu streamsense bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
[ -d /opt/streamsense/app ] || sudo -iu streamsense git clone {REPO} /opt/streamsense/app
sudo -iu streamsense bash -c 'cd /opt/streamsense/app/backend && ~/.local/bin/uv sync --locked --extra gpu'
sudo -iu streamsense bash -c 'cd /opt/streamsense/app/backend && .venv/bin/python - <<PY
import boto3, os
s3 = boto3.client("s3", region_name="{REGION}")
pre = "{prefix}{MODEL_PREFIX}"
for page in s3.get_paginator("list_objects_v2").paginate(Bucket="{bucket}", Prefix=pre):
    for o in page.get("Contents", []):
        dst = os.path.join("/opt/streamsense/run", o["Key"][len(pre):])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        s3.download_file("{bucket}", o["Key"], dst)
PY'
umask 077
cat > /etc/streamsense-worker.env <<'EOF'
{lines}
EOF
chown streamsense /etc/streamsense-worker.env
cat > /etc/systemd/system/streamsense-worker.service <<'EOF'
[Unit]
Description=StreamSense GPU worker
After=network-online.target
[Service]
User=streamsense
WorkingDirectory=/opt/streamsense/app/backend
EnvironmentFile=/etc/streamsense-worker.env
ExecStart=/opt/streamsense/app/backend/.venv/bin/python -m app.worker
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now streamsense-worker
"""


def find(ec2):  # noqa: ANN001, ANN201
    r = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [NAME]},
                                        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])  # fmt: skip
    insts = [i for res in r["Reservations"] for i in res["Instances"]]
    return insts[0] if insts else None


def quota(s) -> float:  # noqa: ANN001
    q = s.client("service-quotas")
    return q.get_service_quota(ServiceCode=QUOTA[0], QuotaCode=QUOTA[1])["Quota"]["Value"]


def register_with_api(instance_id: str) -> None:
    """Add GPU_INSTANCE_ID to the API host's env and restart it (so uploads wake the worker)."""
    import subprocess

    script = (f"sudo sed -i '/^STREAMSENSE_API_GPU_INSTANCE_ID=/d' /etc/streamsense.env && "
              f"echo STREAMSENSE_API_GPU_INSTANCE_ID={instance_id} | sudo tee -a /etc/streamsense.env >/dev/null && "
              f"echo STREAMSENSE_API_GPU_REGION={REGION} | sudo tee -a /etc/streamsense.env >/dev/null && "
              "sudo systemctl restart streamsense-api")  # fmt: skip
    subprocess.run([*ssh_cmd(), script], check=True)


def up() -> None:
    s = session()
    ec2, iam = s.client("ec2"), s.client("iam")
    have = quota(s)
    if have < 4:
        sys.exit(
            f"G-instance vCPU quota in {REGION} is {have:g}; a g6.xlarge needs 4. Wait for the increase."
        )
    env = env_file()
    bucket = env["STREAMSENSE_API_S3_BUCKET"]
    prefix = env.get("STREAMSENSE_API_S3_PREFIX", "streamsense/")
    inst = find(ec2)
    if inst is None:
        worker_env = {
            "STREAMSENSE_API_DB_URL": env["DATABASE_URL_UNPOOLED"],
            "STREAMSENSE_API_MEDIA_BACKEND": "s3",
            "STREAMSENSE_API_S3_BUCKET": bucket,
            "STREAMSENSE_API_S3_PREFIX": prefix,
            "STREAMSENSE_API_S3_REGION": REGION,
            "STREAMSENSE_API_BACKEND": "streamsense",
            "STREAMSENSE_API_RUN_DIR": "/opt/streamsense/run",
            "STREAMSENSE_API_STREAMSENSE_REPO": "/opt/streamsense/app/ml",
            "STREAMSENSE_API_BATCH_SIZE": "16",
            "STREAMSENSE_API_DATA_DIR": "/opt/streamsense/data",
            "STREAMSENSE_API_IDLE_SHUTDOWN_SEC": "900",
            "HF_HOME": "/opt/streamsense/hf",
            "HF_HUB_DISABLE_XET": "1",
        }
        ami = s.client("ssm").get_parameter(
            Name="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"
        )["Parameter"]["Value"]
        inst = ec2.run_instances(
            ImageId=ami, InstanceType="g6.xlarge", MinCount=1, MaxCount=1, KeyName=key_pair(ec2),
            SecurityGroupIds=[security_group(ec2)], IamInstanceProfile={"Name": role(iam, bucket, prefix)},
            UserData=user_data(worker_env, bucket, prefix),
            InstanceInitiatedShutdownBehavior="stop",
            BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 120, "VolumeType": "gp3"}}],
            MetadataOptions={"HttpTokens": "required"},
            TagSpecifications=[{"ResourceType": "instance", "Tags": tag(NAME)}],
        )["Instances"][0]  # fmt: skip
        print("launched", inst["InstanceId"])
    register_with_api(inst["InstanceId"])
    # The cloud GPU now covers the online demo: let PACE's rolling workers wind down.
    stop = Path.home() / ".streamsense" / "stop-pace-workers"
    stop.parent.mkdir(mode=0o700, exist_ok=True)
    stop.touch()
    print(
        json.dumps(
            {"instance": inst["InstanceId"], "api": elastic_ip(ec2)["PublicIp"], "registered": True}
        )
    )


def status() -> None:
    s = session()
    inst = find(s.client("ec2"))
    print(json.dumps({"quota_vcpu": quota(s), "instance": inst and inst["InstanceId"],
                      "state": inst and inst["State"]["Name"], "api_name": API_NAME}))  # fmt: skip


if __name__ == "__main__":
    {"up": up, "status": status}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
