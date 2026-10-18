param([string]$Customer)
docker compose -p $Customer --env-file customers/$Customer.env config --quiet