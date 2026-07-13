## ADDED Requirements

### Requirement: Concurrent sticky-session upserts complete from their committed write

When a sticky-session upsert commits successfully, the operation MUST complete
without depending on a later read or refresh of the same mapping. A concurrent
worker MAY subsequently delete or rebind the mapping, but that newer write MUST
NOT turn the already-committed upsert into a missing-row or refresh exception.

#### Scenario: Concurrent delete wins immediately after upsert commit

- **GIVEN** one worker upserts a `(key, kind)` sticky-session mapping
- **AND** another worker deletes that mapping immediately after the upsert commits
- **WHEN** the upsert operation returns to its caller
- **THEN** it returns the mapping snapshot written by its own database statement
- **AND** it does not raise `StickySession upsert failed`
- **AND** it does not raise a database refresh exception
