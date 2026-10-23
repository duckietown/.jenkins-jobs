# .jenkins-jobs

This repository contains the CI Jobs for Duckietown run by Jenkins.

## Add new Job

You can add a new Job by listing the new repository in the file `repositories.json`.
Once done, regenerate the index using the command,

```shell
make generate-production
```

or 

```shell
make generate-staging
```

Then commit the new changes. Don't worry if you see changes to Jobs you did not update, it is fine.
Commit everything and push. 

Jenkins will automatically pull the new changes, but you will need to tell him to reload the jobs from Disk via "Manage Jenkins" > "Reload Configuration from Disk".

## IMPORTANT:

Jobs should never be modified through Jenkins GUI. Apply changes to the relevant
template under [jobs/](jobs/) and use the generator to update the job configurations.

## Protected Ente image releases

The `release_component` entries in [repositories.json](repositories.json)
select the Engine and Duckietown Viewer for separate maintainer-approved
release jobs. Ordinary Docker Autobuild jobs still publish CI tags. They never
receive the artifact signing credentials, and their unsigned images do not
advance the signed Ente catalogs.

Provision the dedicated exclusive release/signing agents, public trust,
credentials, approval group and controller isolation described in
[ci-jenkins](https://github.com/duckietown/ci-jenkins#protected-ente-image-releases)
before enabling either job.

After the Shell tools have been reviewed and committed, set `SHELL_TOOLS_SHA`
to that full commit SHA and regenerate just these two jobs:

```shell
make generate-protected-releases SHELL_TOOLS_SHA="$SHELL_TOOLS_SHA"
```

The source SHA and version are build parameters; the Shell tools SHA is fixed
by [the job template](jobs/__image_release_template__/config.xml.template) and
[generator](generator/create_image_release_jobs.py), not supplied by whoever
starts a build. Without `SHELL_TOOLS_SHA`, generation deliberately creates
**disabled** jobs. Do not enable those empty-pin jobs through the Jenkins UI.
Regular production/staging generation preserves the separate protected jobs.

Review, commit and push the generated configuration using the normal jobs
deployment process, then **Manage Jenkins > Reload Configuration from Disk**.
The production jobs are:

- `Protected Image Release - ente - dt-duckiematrix`
- `Protected Image Release - ente - dt-duckietown-viewer`

They have no push/upstream trigger. Use **Build with Parameters**, provide the
reviewed full application `SOURCE_SHA` and unused `VERSION`, approve the
maintainer gate, and download `release/engines.json` or
`release/backends.json` from that exact successful build. No DCSS catalog
pointer changes automatically.

The ordinary Engine/Viewer import-only smoke launcher runs directly in the
built image on its native builder, without mounting source or requesting a
developer session. This does not launch an authorized application; actual
startup remains guarded. Other repositories retain the existing DTS smoke
path. Template shell braces are escaped for the Python generator.

Run the focused generator/XML/shell checks without network access:

```shell
python3 -m unittest discover -s tests -p test_image_release_jobs.py
```
