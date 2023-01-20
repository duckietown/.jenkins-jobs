ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

ARCH:="arm32v7,arm64v8,amd64"

_generate:
	# repository jobs
	rm -rf ${ROOT_DIR}/jobs/Docker\ Autobuild*
	rm -rf ${ROOT_DIR}/jobs/Git\ Automerge*
	rm -rf ${ROOT_DIR}/jobs/Stage\ Sync*
	python3 ${ROOT_DIR}/generator/create_repository_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--repos ${ROOT_DIR}/repositories.json \
		--arch ${ARCH} \
		--distro ${DISTRO}
	# webcheck jobs
	rm -rf ${ROOT_DIR}/jobs/Webcheck*
	python3 ${ROOT_DIR}/generator/create_webcheck_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--websites ${ROOT_DIR}/websites.json \
		--labels ${LABELS}

generate-production: DISTRO=daffy,ente
generate-production: LABELS=production
generate-production: _generate

generate-staging: DISTRO=daffy-staging,ente-staging
generate-staging: LABELS=staging
generate-staging: _generate
