#!/bin/bash
# Find the ATS board token/slug behind a company careers page.
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
html=$(curl -sSL -A "$UA" --max-time 20 "$1")
echo "$html" | grep -oiE '(job-boards|boards)(\.eu)?\.greenhouse\.io/(embed/job_board\?for=)?[a-z0-9_-]+' | sed -E 's#.*/##' | grep -v '^embed' | sort -u | sed 's/^/greenhouse: /'
echo "$html" | grep -oiE 'jobs\.lever\.co/[a-z0-9_-]+|api\.lever\.co/v0/postings/[a-z0-9_-]+' | sed -E 's#.*/##' | sort -u | sed 's/^/lever: /'
echo "$html" | grep -oiE 'jobs\.ashbyhq\.com/[a-z0-9_.-]+|api\.ashbyhq\.com/posting-api/job-board/[a-z0-9_.-]+' | sed -E 's#.*/##' | sort -u | sed 's/^/ashby: /'
echo "$html" | grep -oiE '[a-z0-9-]+\.myworkdayjobs\.com/[a-z0-9_-]+' | sort -u | sed 's/^/workday: /'
