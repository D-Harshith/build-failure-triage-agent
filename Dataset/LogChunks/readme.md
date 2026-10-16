# LogChunks

Welcome to the **LogChunks** data set!

We collected 797 Travis CI logs from a wide range of 80 GitHub repositories from 29 different main development languages.
You can find our collection tool in `log-collection` and the logs sorted by language and repository in `logs`.

We manually labeled the part (chunk) of the log describing why the build failed.
In addition, the chunks are annotated with keywords that we would use to search for them and categorized according to their structural representation within the log.
You can find this data in an xml-file for each repository in `build-failure-reason`.

## File Structure
```
root
 |-- readme.md
 |-- repositoryies.txt: the repositories from which the logs in this repository are
 |-- dev-mails-data.csv: results from the validation study
 |
 |-- build-failure-reason: the manually labeled data
 |   '--<main_language>
 |      '--<repo_owner>@<repo_name>.xml
 |
 |-- logs
 |   '--<main_language>
 |      '--<repo_owner>@<repo_name>
 |         '--<build_status>
 |            '--<build_id>.log
 |
 '-- log-collection: our tool for collecting Travis CI build logs
```

## Matching Validation Data to Logs
`dev-mails-data.csv` contains the results from our validation study.  
To find out whether a log was validated as correct, select the row with the corresponding 'build_id'.
If `extraction valid` is true, the original developer reported the log chunk as correct, if `valid - override` the log chunk was marked as correct in the manual answer inspection (we had to trim some log chunks for readability and the developers reported that it shows to few lines).
