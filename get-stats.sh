#!/bin/bash

sqlite3 minitaxa.db "select count(*), dataset.name from taxa left join dataset on dataset.id = taxa.dataset_id group by dataset.name;"

