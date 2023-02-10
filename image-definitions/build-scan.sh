#!/bin/bash
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Build and scan all images one by one.
# Images are built, scanned, and removed to save space.
# Old Trivy reports and summaries are removed prior to scan.
# By default scanned images are cleaned up after every scan. Set CLEANUP_IMAGES to "false" to
# disable image cleanup.
#
# Usage: build-scan.sh <tag> or build-scan.sh
#
set -e

TAG=$1
CLEANUP_IMAGES=true

# Kubeflow container images build and scan
echo "Build image definitions for Kubeflow"
REPO_DIR="kubeflow"
# if not specified, TAG is taken from corresponding version.txt
TAG=${TAG:-$(eval "cat $REPO_DIR/version.txt")}

echo "Tag: $TAG"
export TAG=$TAG
# components to pull from upstream (order is important)
# this list contains directories and modifiers for make command, if applicable
COMPONENTS_LIST=(
"components/access-management"
"components/profile-controller"
)

# remove scan summary file and trivy-reports/
rm -f scan-summary.txt
rm -rf ./trivy-reports/

# perform build and scan for each components
for COMPONENT in "${COMPONENTS_LIST[@]}"; do
	cd "$REPO_DIR/${COMPONENT}"

	echo "Building ${COMPONENT}"
	make docker-build
	cd -

	echo "Scanning images with $TAG"
	# scan will scan all images with specified $TAG
	./scan.sh $TAG

        if [ "$CLEANUP_IMAGES" != true ]; then
                continue
        fi

	echo "Clean up scanned images"
	# the following images should not be cleaned up to avoid rebuild/pulling
	# - base
	# - jupyter
	# - ubuntu
	# - *:debug
	# - aquasec/trivy
	CLEANUP_IMAGE_LIST=($(docker images --format="{{json .}}" | jq -r 'select((.Tag=="$TAG") or (.Repository!="base" and .Repository!="jupyter" and .Repository!="ubuntu" and .Tag!="debug" and .Repository!="aquasec/trivy")) | "\(.Repository):\(.Tag)"'))
	for IMAGE in "${CLEANUP_IMAGE_LIST[@]}"; do
		set +e
		docker rmi $IMAGE 2>/dev/null
		set -e
	done

	echo "Cleanup running containers and intermediate images"
	# stop and remove all running containers
	set +e
	docker stop $(docker ps -aq)
	docker rm $(docker ps -aq)
        docker rmi $(docker images --filter=dangling=true -q) 2>/dev/null
	set -e
done

# End of Kubeflow container images build and scan

echo "Done."
