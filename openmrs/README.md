README.md for openmrs config
============================

# setup SDK

Please specify your container id/name/label (you can get it using command `docker ps -a --no-trunc`): imladris-mysql
Please specify DB username: openmrs
Please specify DB password: openmrs
Please specify database uri (-DdbUri) (default: 'jdbc:mysql://localhost:3308/server'): jdbc:mysql://localhost:3306/openmrs_imladris01
jdbc:mysql://localhost:3306/openmrs_imladris01

```
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-11.jdk/Contents/Home
mvn openmrs-sdk:run -DserverId=imladris01
```


# Git repos

Let each project clone its own build env at specific versions.

If/when we want to do local updates, clone the forks and create an 'imladris' branch.
```
for repo in openmrs-distro-pihemr openmrs-frontend-pihemr openmrs-config-zl openmrs-distro-zl; do
  cd $repo
  git checkout -b imladris
  git push -u origin imladris
  echo "✓ $repo"
  cd ..
done
```

# MySQL

To get a MySQL root session:

docker exec -it imladris-mysql mysql -u root -prootpw

To create the database:

CREATE DATABASE IF NOT EXISTS openmrs_imladris01;
GRANT ALL PRIVILEGES ON openmrs_imladris01.* TO 'openmrs'@'%';
FLUSH PRIVILEGES;



# radiology module references

https://pihemr.atlassian.net/wiki/spaces/HAIT/pages/256967454/Radiology

https://pihemr.atlassian.net/wiki/spaces/HAIT/pages/256967458/PACS+Integration+Technical+Overview

