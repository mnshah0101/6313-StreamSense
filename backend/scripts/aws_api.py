"""Deploy the StreamSense API (no GPU) to one EC2 instance with HTTPS. Idempotent.

  python scripts/aws_api.py up       # create or reuse everything; prints the API URL
  python scripts/aws_api.py update   # pull the latest code from GitHub and restart (via SSH)
  python scripts/aws_api.py ssh      # print the SSH command

Uses the AWS profile in $AWS_PROFILE (default streamsense-deploy) and region us-east-2.
Reads DATABASE_URL_UNPOOLED and the S3 bucket from backend/.env. Creates: key pair
"streamsense" (private key saved to ~/.streamsense/streamsense-ec2.pem), security group
"streamsense-api" (22/80/443), IAM role "streamsense-api" (S3 prefix + start the GPU worker),
an Elastic IP, and a t3.small Ubuntu 24.04 instance running uvicorn behind Caddy, which gets a
TLS certificate for <elastic-ip>.sslip.io. The API runs no worker (GPU workers elsewhere).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
NAME = "streamsense-api"
REPO = "https://github.com/mnshah0101/6313-StreamSense.git"
HOME = Path.home() / ".streamsense"
KEY_PATH = HOME / "streamsense-ec2.pem"
API_DIR = Path(__file__).resolve().parents[1]


def env_file() -> dict[str, str]:
    out = {}
    for line in (API_DIR / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def session() -> boto3.Session:
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "streamsense-deploy"), region_name=REGION)


def tag(name: str) -> list[dict]:
    return [{"Key": "Name", "Value": name}, {"Key": "project", "Value": "streamsense"}]


def key_pair(ec2) -> str:  # noqa: ANN001
    try:
        ec2.describe_key_pairs(KeyNames=["streamsense"])
        if not KEY_PATH.exists():
            sys.exit(f"key pair 'streamsense' exists but {KEY_PATH} is missing")
    except ClientError:
        HOME.mkdir(mode=0o700, exist_ok=True)
        k = ec2.create_key_pair(KeyName="streamsense", KeyType="ed25519")
        KEY_PATH.write_text(k["KeyMaterial"])
        KEY_PATH.chmod(0o600)
    return "streamsense"


def security_group(ec2) -> str:  # noqa: ANN001
    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [NAME]}])["SecurityGroups"]
    if found:
        return found[0]["GroupId"]
    sg = ec2.create_security_group(GroupName=NAME, Description="StreamSense API: SSH, HTTP, HTTPS", VpcId=vpc)["GroupId"]
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}
        for p in (22, 80, 443)
    ])  # fmt: skip
    return sg


def role(iam, bucket: str, prefix: str) -> str:  # noqa: ANN001
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
             "Action": "sts:AssumeRole"}]}  # fmt: skip
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
         "Resource": f"arn:aws:s3:::{bucket}/{prefix}*"},
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"], "Resource": f"arn:aws:s3:::{bucket}"},
        {"Effect": "Allow", "Action": ["ec2:DescribeInstances", "ec2:StartInstances"], "Resource": "*"},
    ]}  # fmt: skip
    try:
        iam.get_role(RoleName=NAME)
    except ClientError:
        iam.create_role(RoleName=NAME, AssumeRolePolicyDocument=json.dumps(trust), Tags=tag(NAME))
    iam.put_role_policy(RoleName=NAME, PolicyName="streamsense-api", PolicyDocument=json.dumps(policy))
    try:
        iam.get_instance_profile(InstanceProfileName=NAME)
    except ClientError:
        iam.create_instance_profile(InstanceProfileName=NAME)
        iam.add_role_to_instance_profile(InstanceProfileName=NAME, RoleName=NAME)
        time.sleep(10)  # IAM propagation
    return NAME


def user_data(host: str, env: dict[str, str]) -> str:
    lines = "\n".join(f"{k}={v}" for k, v in env.items())
    return f"""#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl gnupg debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy
id streamsense || useradd -r -m -d /opt/streamsense -s /bin/bash streamsense
sudo -iu streamsense bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
[ -d /opt/streamsense/app ] || sudo -iu streamsense git clone {REPO} /opt/streamsense/app
sudo -iu streamsense bash -c 'cd /opt/streamsense/app/backend && ~/.local/bin/uv sync --locked'
mkdir -p /var/lib/streamsense && chown streamsense /var/lib/streamsense
umask 077
cat > /etc/streamsense.env <<'EOF'
{lines}
EOF
chown streamsense /etc/streamsense.env
cat > /etc/systemd/system/streamsense-api.service <<'EOF'
[Unit]
Description=StreamSense API
After=network-online.target
[Service]
User=streamsense
WorkingDirectory=/opt/streamsense/app/backend
EnvironmentFile=/etc/streamsense.env
ExecStart=/opt/streamsense/app/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/caddy/Caddyfile <<'EOF'
{host} {{
  reverse_proxy 127.0.0.1:8000
}}
EOF
systemctl daemon-reload
systemctl enable --now streamsense-api
systemctl restart caddy
"""


def find_instance(ec2):  # noqa: ANN001, ANN201
    r = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [NAME]},
                                        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])  # fmt: skip
    insts = [i for res in r["Reservations"] for i in res["Instances"]]
    return insts[0] if insts else None


def elastic_ip(ec2) -> dict:  # noqa: ANN001
    found = ec2.describe_addresses(Filters=[{"Name": "tag:Name", "Values": [NAME]}])["Addresses"]
    if found:
        return found[0]
    a = ec2.allocate_address(Domain="vpc", TagSpecifications=[{"ResourceType": "elastic-ip", "Tags": tag(NAME)}])
    return {"AllocationId": a["AllocationId"], "PublicIp": a["PublicIp"]}


def up() -> None:
    s = session()
    ec2, iam = s.client("ec2"), s.client("iam")
    env = env_file()
    bucket = env["STREAMSENSE_API_S3_BUCKET"]
    prefix = env.get("STREAMSENSE_API_S3_PREFIX", "streamsense/")
    eip = elastic_ip(ec2)
    host = f"{eip['PublicIp'].replace('.', '-')}.sslip.io"
    inst = find_instance(ec2)
    if inst is None:
        api_env = {
            "STREAMSENSE_API_DB_URL": env["DATABASE_URL_UNPOOLED"],
            "STREAMSENSE_API_MEDIA_BACKEND": "s3",
            "STREAMSENSE_API_S3_BUCKET": bucket,
            "STREAMSENSE_API_S3_PREFIX": prefix,
            "STREAMSENSE_API_S3_REGION": REGION,
            "STREAMSENSE_API_EMBEDDED_WORKER": "false",
            "STREAMSENSE_API_BACKEND": "dummy",  # placeholder; /model reports the GPU workers
            "STREAMSENSE_API_AUTH_MODE": "session",
            "STREAMSENSE_API_COOKIE_SECURE": "true",
            "STREAMSENSE_API_DATA_DIR": "/var/lib/streamsense",
            "STREAMSENSE_API_CORS_ORIGIN_REGEX": r"https://.*\.vercel\.app",
        }
        ami = s.client("ssm").get_parameter(
            Name="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
        )["Parameter"]["Value"]
        inst = ec2.run_instances(
            ImageId=ami, InstanceType="t3.small", MinCount=1, MaxCount=1, KeyName=key_pair(ec2),
            SecurityGroupIds=[security_group(ec2)], IamInstanceProfile={"Name": role(iam, bucket, prefix)},
            UserData=user_data(host, api_env),
            BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 20, "VolumeType": "gp3"}}],
            MetadataOptions={"HttpTokens": "required"},
            TagSpecifications=[{"ResourceType": "instance", "Tags": tag(NAME)}],
        )["Instances"][0]  # fmt: skip
        print("launched", inst["InstanceId"])
    iid = inst["InstanceId"]
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    if eip.get("InstanceId") != iid:
        ec2.associate_address(AllocationId=eip["AllocationId"], InstanceId=iid)
    print(json.dumps({"instance": iid, "ip": eip["PublicIp"], "url": f"https://{host}"}))


def ssh_cmd() -> list[str]:
    ec2 = session().client("ec2")
    eip = elastic_ip(ec2)
    return ["ssh", "-i", str(KEY_PATH), "-o", "StrictHostKeyChecking=accept-new", f"ubuntu@{eip['PublicIp']}"]


def update() -> None:
    script = ("sudo -iu streamsense bash -c 'cd /opt/streamsense/app && git pull -q && cd backend && "
              "~/.local/bin/uv sync --locked -q' && sudo systemctl restart streamsense-api && "
              "sleep 3 && curl -s localhost:8000/health")  # fmt: skip
    subprocess.run([*ssh_cmd(), script], check=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "up"
    {"up": up, "update": update, "ssh": lambda: print(" ".join(ssh_cmd()))}[cmd]()
