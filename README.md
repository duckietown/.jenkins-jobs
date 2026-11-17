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

Jobs should never be modified through Jenkins GUI. Changes should be applied to the template in the 
`templates/` of this repository and then use the generator tool to update all jobs.

## Hand-maintained jobs

A few jobs are not generated from `repositories.json` — the Workspace image build, for instance, runs a plain
`docker build` and has no `dtproject` behind it. The generator deletes and rewrites every job whose name starts
with one of its own prefixes (`Docker Autobuild`, `Git Automerge`, `Stage Sync`, `Distro Sync`, `CodeBook Build`,
`Book Build`, `Webcheck`), so a hand-written job must not use any of them, or it disappears the next time someone
regenerates. Name it something else; `Image Build - ...` is what the Workspace builds use.

