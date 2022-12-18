ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

ARCH:="arm32v7,arm64v8,amd64"

_generate:
	rm -rf ${ROOT_DIR}/jobs/Docker\ Autobuild*
	rm -rf ${ROOT_DIR}/jobs/Git\ Automerge*
	python3 ${ROOT_DIR}/generator/create_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--repos ${ROOT_DIR}/repositories.json \
		--arch ${ARCH} \
		--distro ${DISTRO}

generate-production: DISTRO=daffy,ente
generate-production: _generate

generate-staging: DISTRO=daffy-staging,ente-staging
generate-staging: _generate
