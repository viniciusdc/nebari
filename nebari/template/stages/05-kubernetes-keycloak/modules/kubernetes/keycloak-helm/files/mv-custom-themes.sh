#!/bin/sh

if [ -d /opt/data/themes ]; then
  echo 'Copying custom themes from /opt/data/themes to /opt/jboss/keycloak/themes'
  cp -r /opt/data/themes/* /opt/jboss/keycloak/themes/
else
  echo 'No custom themes found in /opt/data/themes'
fi