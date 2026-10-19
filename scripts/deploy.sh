#!/bin/sh
set -eu

stack=aiip-auth
service=${stack}_auth
image=aiip-auth

tag=$(docker image inspect -f '{{.Id}}' "$image:latest" | cut -d: -f2 | cut -c1-12)
docker tag "$image:latest" "$image:$tag"

deployed=$(docker service inspect -f '{{.Spec.TaskTemplate.ContainerSpec.Image}}' "$service" 2>/dev/null || true)
replicas=${1:-$(docker service inspect -f '{{.Spec.Mode.Replicated.Replicas}}' "$service" 2>/dev/null || echo 1)}

case "$deployed" in
    "$image:$tag"*) ;;
    *) docker run --rm --network aiip -v "$PWD/config.toml:/app/config.toml:ro" "$image:$tag" alembic upgrade head ;;
esac

IMAGE_TAG=$tag \
REPLICAS=$replicas \
CONFIG_HASH=$(cksum < config.toml | cut -d' ' -f1) \
KEY_HASH=$(cksum < keys/private.pem | cut -d' ' -f1) \
docker stack deploy --detach=false --resolve-image never -c stack.yaml "$stack"

state=$(docker service inspect -f '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}' "$service")
case "$state" in
    rollback_*)
        echo "$service: выкатка не прошла, вернулась прошлая версия"
        exit 1
        ;;
esac

docker config ls -q --filter "label=com.docker.stack.namespace=$stack" | xargs docker config rm >/dev/null 2>&1 || true
docker secret ls -q --filter "label=com.docker.stack.namespace=$stack" | xargs docker secret rm >/dev/null 2>&1 || true
docker image ls --format '{{.Repository}}:{{.Tag}}' "$image" | grep -vx -e "$image:latest" -e "$image:$tag" | xargs docker rmi >/dev/null 2>&1 || true
