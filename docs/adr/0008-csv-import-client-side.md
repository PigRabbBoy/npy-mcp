# CSV import is client-side parsing + saveTransactionsFanout

Notion's CSV import (discovered via network capture) is entirely client-side:
the browser JS parses the CSV, maps headers to property types, and sends the
resulting blocks via `saveTransactionsFanout`. There is no server-side import
endpoint that accepts a file and returns blocks. We decided to replicate
this: `import_csv` parses the CSV locally using Python's `csv` module, builds
a collection + schema + rows, and submits via the same `saveTransactionsFanout`
path. The alternative was to upload the file to S3 via
`getUploadSpaceFileUrl` and trigger server-side import, but the server-side
path requires `enqueueCsvImportIndexing` and additional steps that are harder
to control. Client-side parsing gives us full control over column type
mapping and error handling.