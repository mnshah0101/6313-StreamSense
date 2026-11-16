"""Hydra entry point; implementation scheduled for delivery stage 6."""

from streamsense.stages import deferred_entrypoint

main = deferred_entrypoint("bench", 6)


if __name__ == "__main__":
    main()
