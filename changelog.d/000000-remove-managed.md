### Removed
- API 25: remove legacy `attempt_id` spawn and spawn-status queries, the managed spawn controller, and separate dsh/Hermes runtime layers with mandatory usage and egress gates. DeepSeek and Local use standard spawn, name-based status, native resume, and shared cleanup.
