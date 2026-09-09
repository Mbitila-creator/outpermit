# Database normalization review

This review covers the Django data model used by OutPermit before production
deployment. The schema is relational and is designed around third normal form
(3NF), with a small number of intentional snapshot fields needed for auditable
government workflows.

## Normalized areas

- Ministry structure is separated into departments, hierarchical department
  units, user profiles, approval roles and module-role assignments.
- Permit group members are stored as child rows rather than repeated columns.
- Tasks, assignees and progress updates are separate relations.
- Event categories, venues, events and category-specific operational records
  are separate relations.
- Questionnaire forms, sections, questions, choices, condition groups,
  submissions and typed answers are separate relations.
- Multi-select questionnaire responses use a junction table.
- Finance requests, budget lines, approvals, disbursements, retirements,
  retirement lines and documents are separate relations.
- Meeting sessions, attendees, resources, acknowledgements, decisions and
  actions are separate relations.
- Conference and learning-event speakers/facilitators use relational links.

## Corrections in this review

1. `Department.has_units` was persisted even though it is entirely determined
   by related active `DepartmentUnit` rows. It is now a computed property,
   preventing stale values and removing a transitive/derived dependency.
2. `TaskAssignment` had two Python `save()` definitions. The second definition
   overrode synchronization of the MariaDB-compatible group-leader marker.
   The logic is consolidated, and a data migration repairs historical markers
   while deterministically retaining one leader where inconsistent rows exist.

## Intentional denormalization

The following values must remain because they are historical snapshots rather
than competing sources of current master data:

- requester, group-leader and acting-officer names/employee details recorded
  on permit requests;
- participant badge names, organizations and titles;
- approval comments, decision metadata and notification recipients;
- imported source row identifiers;
- calculated workflow history and immutable public reference numbers.

Removing these fields would cause old approvals, certificates and audit records
to change when a user profile changes. They are therefore deliberate audit
snapshots and are compatible with the system's record-retention requirements.

## JSON fields

JSON is limited to expression operands and immutable executive workflow
snapshots. Frequently filtered operational entities are represented by normal
tables and foreign keys. JSON values should not be expanded into new tables
unless reporting requirements begin to query individual JSON elements.

## Deployment controls

Before each deployment:

1. Create a logical database backup and media archive.
2. Run `python manage.py migrate`.
3. Run `python manage.py check --database default`.
4. Run `python manage.py makemigrations --check --dry-run`.
5. Run the complete test suite against the target database engine.
6. Verify foreign-key checks remain enabled and inspect migration output.

Schema changes must be made through Django migrations. Database dumps, `.env`
files, passwords and uploaded media must not be committed to Git.
