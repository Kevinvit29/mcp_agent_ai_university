# Admin General AI + University Database Mode

This version changes the admin behavior to act like:

> ChatGPT-style general AI + full university database access.

## Behavior

Admin can ask:

- General questions, e.g. `explain machine learning`, `write an email`, `what is photosynthesis?`
- University database questions, e.g. `give me S001 profile`, `list all students`, `summarize all grades`
- University document questions, e.g. `what PDFs are uploaded?`, `explain the writing report PDF`, `summarize this Excel file`
- Broad university audit questions, e.g. `what can you access in the university system?`, `summarize everything`

## Routing rule

The chat now decides:

1. If the question needs private/university data → use MCP/database tools.
2. If the question asks about PDFs, Excel files, CSV files, or stored documents → use Postgres/MongoDB knowledge tools.
3. If the question asks general world knowledge → answer directly with OpenAI.
4. If the question needs current/live internet facts → say a web-search tool is needed for real-time verification.

## Important

The model must not invent university data. All private data must come from MongoDB/Postgres/MCP tools.

This version does not add live internet search or image chat upload UI. To make it fully like ChatGPT with screenshots/images, add:

- frontend chat image upload
- backend `/chat/image` endpoint
- OpenAI vision request
- optional database lookup after the image is interpreted
