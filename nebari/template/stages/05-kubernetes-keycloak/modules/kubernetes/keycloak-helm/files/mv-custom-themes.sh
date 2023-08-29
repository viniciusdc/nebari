#!/bin/sh

if [ -d /opt/data/custom-themes ]; then
  echo 'Copying custom themes from /opt/data/custom-themes to /opt/jboss/keycloak/themes'
  cp -r /opt/data/custom-themes/* /opt/jboss/keycloak/themes/
else
  echo 'No custom themes found in /opt/data/custom-themes'
fi