#!/bin/bash
dbname=minitaxa.db

sqlite3 $dbname < data/sql/schema.sql
sqlite3 $dbname < data/sql/data-taxa-rank.sql
sqlite3 $dbname < data/sql/data-status.sql
sqlite3 $dbname < data/sql/create-index.sql

