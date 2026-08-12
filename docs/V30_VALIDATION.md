# V30 Validation Record

The release was checked before packaging with:

- Python module compilation for backend, MCP server, and scripts.
- YAML parsing for both Docker Compose files.
- 58 automated backend and release-integrity tests, all passing.
- ZIP integrity verification after packaging.

The build environment did not have working DNS access to `registry.npmjs.org`, so an independent frontend `npm ci`/Vite production build could not be rerun here. The frontend Dockerfile uses a locked `package-lock.json`, the public npm registry, and `npm ci --include=dev`; the Windows launcher performs the real Docker build on the installation machine.

Docker Engine was not available in the build environment, so live container startup and browser smoke testing must occur on the destination machine. `START_V30.bat` waits for the real backend/frontend health checks and reports failure logs instead of opening a stale application.
