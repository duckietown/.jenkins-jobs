# .jenkins-jobs

This repository contains the CI Jobs for Duckietown run by Jenkins.

## Add new Job

You can add a new Job by listing the new repository in the file `repositories.json`.
Once done, regenerate the index using the command,

```
make generate
```

Then commit the new changes, do ont worry if you see changes to Jobs you did not update, it is fine.
Commit everything and push. 

Jenkins will automatically pull the new changes, but you will need to tell him to reload the jobs from Disk via "Manage Jenkins" > "Reload Configuration from Disk".

## IMPORTANT:

Jobs should never be modified through Jenkins GUI. Changes should be applied to the template in the 
`templates/` of this repository and then use the generator tool to update all jobs.
