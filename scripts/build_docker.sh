#!/usr/bin/env bash
set -euo pipefail

DOCKERFILE="${DOCKERFILE:-docker/Dockerfile}"
CONTEXT="${DOCKER_CONTEXT:-.}"
IMAGE="${DOCKER_IMAGE:-}"
PLATFORMS="${DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"
TARGET="${DOCKER_TARGET:-}"
PUSH=true
LOAD=false

usage() {
  cat <<'USAGE'
Usage: ./scripts/build_docker.sh --image <repository:tag> [options]

Build any Dockerfile in this course repository. A Dockerfile need not use
multi-stage targets; omit --target to build its final stage.

Options:
  --image <repository:tag>  Image tag to build (or set DOCKER_IMAGE).
  --dockerfile <path>       Dockerfile path (default: docker/Dockerfile).
  --context <path>          Build context (default: .).
  --target <stage>          Optional multi-stage Docker build target.
  --platforms <list>        Buildx platforms (default: linux/amd64,linux/arm64).
  --no-push                 Do not push the built image.
  --load                    Load a single-platform image into local Docker.
  -h, --help                Show this help message.

Examples:
  ./scripts/build_docker.sh --image ghcr.io/acme/cst463:latest
  ./scripts/build_docker.sh --image acme/cst463-grader:latest --target grading
  ./scripts/build_docker.sh --image cst463:dev --platforms linux/arm64 --no-push --load
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE=${2:?Error: --image requires a value}
      shift 2
      ;;
    --dockerfile)
      DOCKERFILE=${2:?Error: --dockerfile requires a value}
      shift 2
      ;;
    --context)
      CONTEXT=${2:?Error: --context requires a value}
      shift 2
      ;;
    --target)
      TARGET=${2:?Error: --target requires a value}
      shift 2
      ;;
    --platforms)
      PLATFORMS=${2:?Error: --platforms requires a value}
      shift 2
      ;;
    --no-push)
      PUSH=false
      shift
      ;;
    --load)
      LOAD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option '$1'" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$IMAGE" ]]; then
  echo "Error: --image (or DOCKER_IMAGE) is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$DOCKERFILE" ]]; then
  echo "Error: Dockerfile not found: $DOCKERFILE" >&2
  exit 1
fi

if [[ ! -d "$CONTEXT" ]]; then
  echo "Error: build context is not a directory: $CONTEXT" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is required." >&2
  exit 1
fi

if [[ "$LOAD" == true && "$PLATFORMS" == *,* ]]; then
  echo "Error: --load supports exactly one platform; use --platforms with one value." >&2
  exit 1
fi

if [[ "$PUSH" == false && "$LOAD" == false && "$PLATFORMS" == *,* ]]; then
  echo "Error: a multi-platform build must use --push or --load with one platform." >&2
  exit 1
fi

cmd=(docker buildx build --file "$DOCKERFILE" --platform "$PLATFORMS" --tag "$IMAGE")
if [[ -n "$TARGET" ]]; then
  cmd+=(--target "$TARGET")
fi
if [[ "$PUSH" == true ]]; then
  cmd+=(--push)
fi
if [[ "$LOAD" == true ]]; then
  cmd+=(--load)
fi
cmd+=("$CONTEXT")

echo "Building $IMAGE from $DOCKERFILE (platforms=$PLATFORMS, push=$PUSH, load=$LOAD)"
"${cmd[@]}"
