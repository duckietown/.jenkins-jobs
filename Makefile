ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
BRANCH_NAME=$(shell git rev-parse --abbrev-ref HEAD)

ARCH:="arm32v7,arm64v8,amd64"

_generate_repojobs:
	# repository jobs
	rm -rf ${ROOT_DIR}/jobs/Docker\ Autobuild*
	rm -rf ${ROOT_DIR}/jobs/Git\ Automerge*
	rm -rf ${ROOT_DIR}/jobs/Stage\ Sync*
	rm -rf ${ROOT_DIR}/jobs/Distro\ Sync*
	rm -rf ${ROOT_DIR}/jobs/CodeBook\ Build*
	python3 ${ROOT_DIR}/generator/create_repository_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--repos ${ROOT_DIR}/repositories.json \
		--arch ${ARCH} \
		--distro ${DISTRO} \
		--debug

_generate_webcheck:
	# webcheck jobs
	rm -rf ${ROOT_DIR}/jobs/Webcheck*
	python3 ${ROOT_DIR}/generator/create_webcheck_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--websites ${ROOT_DIR}/websites.json \
		--labels ${LABELS}

_generate_bookbuild:
	# bookbuild jobs
	rm -rf ${ROOT_DIR}/jobs/Book\ Build*
	rm -rf ${ROOT_DIR}/jobs/Git\ Automerge\ -\ Book\ -*
	rm -rf ${ROOT_DIR}/jobs/Stage\ Sync\ -\ Book\ -*
	rm -rf ${ROOT_DIR}/jobs/Distro\ Sync\ -\ Book\ -*
	python3 ${ROOT_DIR}/generator/create_bookbuild_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--books ${ROOT_DIR}/books.json \
		--distro ${DISTRO}

generate-production: DISTRO=daffy,ente
generate-production: LABELS=production
generate-production: _generate_repojobs _generate_webcheck _generate_bookbuild

generate-staging: DISTRO=daffy-staging,ente-staging
generate-staging: LABELS=staging
generate-staging: _generate_repojobs _generate_webcheck _generate_bookbuild

generate: generate-${BRANCH_NAME}
