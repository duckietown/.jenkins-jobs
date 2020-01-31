ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

ARCH:="arm32v7,amd64"
MAJOR:="daffy,ente"

h:
	echo ${ROOT_DIR}

generate:
	rm -rf ${ROOT_DIR}/jobs/Docker*
	python3 ${ROOT_DIR}/generator/create_jobs.py \
		--jobsdir ${ROOT_DIR}/jobs/ \
		--repos ${ROOT_DIR}/repositories.json \
		--arch ${ARCH} \
		--major ${MAJOR}
