# Media blocks accept both URL and file upload

Media blocks (image, video, audio, file, pdf) can be created from a URL or
from a local file. We decided to support both paths in a single
`create_media` tool: if `file_path` is provided, the file is uploaded via
Notion's `getUploadFileUrl` → S3 PUT flow (already implemented in
`EmbedOrUploadBlock.upload_file`); if `url` is provided, the source and
display_source are set directly. The alternative was URL-only, which would
exclude agents that generate content locally (charts, screenshots, PDFs).