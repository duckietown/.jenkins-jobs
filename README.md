# .jenkins-jobs

This repository contains the CI Jobs for Duckietown run by Jenkins.

Jobs should never be modified through Jenkins GUI. Changes should be applied to the template in the 
`templates/` of this repository and then use the generator tool to update all jobs, then commit, push, 
and pull on the other side.

NOTE: Do not forget to tell Jenkins to reload from disk to apply the new changes.
