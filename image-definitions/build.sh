#!/bin/bash
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Build all images
#
# Usage: build.sh <tag> or build.sh
#
set -e

TAG=$1

# Kubeflow container images build
echo "Build image definitions for Kubeflow"
REPO_DIR="kubeflow"
# if not specified, TAG is taken from corresponding version.txt
TAG=${TAG:-$(eval "cat $REPO_DIR/version.txt")}

echo "Tag: $TAG"

echo "Build KFAM"
cd $REPO_DIR/components/access-management
export IMG=kfam
make docker-build TAG=$TAG
echo "Clean up intermediate images"
set +e
docker rmi $(docker images --filter=dangling=true -q) 2>/dev/null
set -e
cd -

echo "Build Profile controller"
cd $REPO_DIR/components/profile-controller
export IMG=profile-controller
make docker-build TAG=$TAG
echo "Clean up intermediate images"
set +e
docker rmi $(docker images --filter=dangling=true -q) 2>/dev/null
set -e
cd -

echo "Clean up intermediate images"
set +e
docker rmi $(docker images --filter=dangling=true -q) 2>/dev/null
docker rmi $(docker images --filter=reference=*:latest -q) 2>/dev/null
set -e

# End of Kubeflow container images build

echo "Docker images ready"
docker images

echo "Done."
