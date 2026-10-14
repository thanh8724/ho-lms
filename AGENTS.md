# Ho PullData Streamlit — Implementation Plan

## 0. Instructions for every agent

Read this file before changing anything in this project.

This document is the shared implementation plan and source of truth for the
Streamlit migration. Agents must preserve the existing business behavior and
must not rewrite LMS queries or export semantics without updating the
compatibility tests first.

Current source application:

```text
../pulldata-app-python
```

The source application is a PyQt6 desktop app. This project is its new
Streamlit implementation.

Hard constraints:

- Do not use Docker.
- The app must deploy on Streamlit Community Cloud.
- Do not include PyQt6 or PyInstaller in the new project.
- Do not commit `.env`, token cache, refresh token, cookies, or real exports.
- Preserve the current GraphQL payloads, filters, CSV columns, sorting,
  timezone handling, fallback behavior, and default values unless a
  compatibility test explicitly approves a change.
- Prefer small, reviewable changes. Run the relevant tests after each phase.

## 1. Product goal

Build a modern Vietnamese Streamlit web app named `Ho PullData` with all data
export features currently available in the desktop app:

1. Request Teacher
2. Survey
3. Sản phẩm học viên
4. Completion học viên
5. Điểm danh giáo viên
6. Office Hours
7. Export Class Observe

The primary deployment target is Streamlit Community Cloud. The first release
targets one trusted LMS account configured through Cloud Secrets. A later
release may support per-user LMS accounts.

## 2. Existing source inventory

Reuse the domain logic from these files with minimal mechanical changes:

| Responsibility | Existing source |
|---|---|
| LMS/Firebase token, refresh, cookie, browser login | `../pulldata-app-python/lms_auth.py` |
| Request Teacher API and CSV export | `../pulldata-app-python/requestTC_fetch.py` |
| Survey API, enrichment, diagnostics, CSV export | `../pulldata-app-python/export_survey.py` |
| Student products detail/summary export | `../pulldata-app-python/getproductb12-13.py` |
| Completion export | `../pulldata-app-python/completion_export.py` |
| Teacher attendance export | `../pulldata-app-python/teacher_attendance_export.py` |
| Office Hours export | `../pulldata-app-python/office_hours.py` |
| Class Observe export | `../pulldata-app-python/get_class.py` |
| Current orchestration behavior | `../pulldata-app-python/controllers.py` |
| Current UI behavior and design tokens | `../pulldata-app-python/ui/` |

Do not port the PyQt signal/slot UI. Extract or wrap the export functions and
replace only the UI orchestration layer.

## 3. Required project structure

Create this structure incrementally:

```text
ho-pulldata-streamlit/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── assets/
│   └── logo.png
├── .streamlit/
│   └── config.toml
├── pulldata/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── service.py
│   │   ├── token_store.py
│   │   └── cloud_auth.py
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── graphql_client.py
│   │   ├── http_session.py
│   │   └── retry_policy.py
│   ├── exports/
│   │   ├── __init__.py
│   │   ├── request_teacher.py
│   │   ├── survey.py
│   │   ├── products.py
│   │   ├── completion.py
│   │   ├── teacher_attendance.py
│   │   ├── office_hours.py
│   │   └── class_observe.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── filter_service.py
│   │   ├── export_service.py
│   │   ├── artifact_service.py
│   │   └── history_service.py
│   └── runtime/
│       ├── __init__.py
│       ├── job_manager.py
│       ├── progress.py
│       └── logging.py
├── ui/
│   ├── __init__.py
│   ├── theme.py
│   ├── layout.py
│   ├── sidebar.py
│   ├── auth_panel.py
│   ├── filter_form.py
│   ├── job_panel.py
│   ├── history_table.py
│   └── components.py
└── tests/
    ├── fixtures/
    ├── test_auth.py
    ├── test_filters.py
    ├── test_exports.py
    ├── test_csv_contracts.py
    ├── test_jobs.py
    └── test_streamlit_ui.py
```

The filenames may be adjusted when an agent finds a better separation, but
the boundaries must remain: authentication, API client, domain exporters,
runtime jobs, and UI should not be mixed together.

## 4. Functional requirements

### 4.1 Shared authentication

The app must provide:

- token status;
- account email;
- token expiry;
- refresh token;
- check token;
- logout/reset session;
- clear error messages without exposing secrets.

For Community Cloud, use a cloud authentication path based on Secrets:

```toml
LMS_WEB_URL = "https://lms.mindx.edu.vn"
LMS_API_URL = "https://lms-api.mindx.edu.vn"
LMS_GRAPHQL_URL = "https://lms-api.mindx.edu.vn/graphql"
LMS_FIREBASE_PROJECT_ID = "mindx-edu-prod"
LMS_FIREBASE_API_KEY = "..."
LMS_REFRESH_TOKEN = "..."
```

The existing headful Playwright login is for local token acquisition only and
must not be required by the Cloud runtime. A password-style token input may be
provided as a fallback, but it must remain session-only and must never be
written to disk or logs.

The initial Cloud deployment is private and uses one trusted LMS account.
Per-user LMS authentication is a later phase and must not be simulated with a
shared token.

### 4.2 Data modules

Implement all seven modules with the current filters and defaults.

#### Request Teacher

- date range;
- date field `startDate` or `endDate`;
- course line;
- course;
- centre;
- class IDs;
- request status;
- satisfaction status;
- optional advanced request type/status filters;
- dynamic class search;
- current 31-column CSV schema.

#### Survey

- submitted date range;
- course line;
- course;
- centre;
- class IDs;
- configured survey IDs and question IDs;
- optional advanced metadata/session/status/feedback filters;
- current diagnostics for missing class/session information;
- dynamic question columns and current base columns.

#### Student products

- date range;
- sessions, defaulting to the current product defaults;
- class statuses;
- course line;
- course;
- centre;
- class IDs;
- class search;
- detail CSV;
- summary CSV;
- ZIP download containing both files.

#### Completion

- date range;
- date field;
- class statuses;
- course line;
- course;
- centre;
- class IDs;
- class search;
- current completion CSV schema.

#### Teacher attendance

- date range;
- sessions;
- class statuses;
- course line;
- course;
- centre;
- class IDs;
- class search;
- teacher timesheet lookup;
- legacy role mapping;
- fallback attendance status logic;
- backend connection retry/backoff;
- current 17-column CSV schema.

#### Office Hours

- date range;
- centre;
- Trial/Fixed type;
- appointment course-line enrichment;
- current Office Hours CSV schema.

#### Class Observe

- date range;
- XART/C4K/ROB blocks;
- class statuses;
- class IDs;
- existing class keyword exclusions;
- existing session exclusions;
- lecturer role filtering;
- current Class Observe CSV schema.

## 5. Data Workspace UI Kit

The UI must follow this design system for every screen and component.

### 5.1 Design direction

- Clean Enterprise, light-first.
- Support light, dark, and system-auto modes through the in-app settings.
- Desktop-first, with responsive behavior for tablet widths.
- Data-focused and operational rather than decorative.
- Dense enough for filters and tables, but with clear hierarchy and readable
  whitespace.
- Use native Streamlit components wherever possible.
- Use Material Symbols icons for navigation and actions instead of emoji.
- Use sentence casing for Vietnamese labels and headings.
- Keep connection controls collapsed by default in a lower sidebar section.
- Long-running exports must expose live logs while the worker is running.
- Dashboard screens use a clear shell hierarchy: navigation, page toolbar, summary
  metrics, filter card, then task/log area.
- The main workspace follows a four-step workflow: module selection, filter
  configuration, processing/log review, and result download.

### 5.2 Color tokens

Define these tokens centrally in `ui/theme.py` and mirror them in
`.streamlit/config.toml` where Streamlit theme tokens support them.

| Token | Value | Intended use |
|---|---|---|
| `background` | `#F6F8FB` | App background |
| `sidebar` | `#FFFFFF` | Sidebar background |
| `surface` | `#FFFFFF` | Cards, panels, filters, tables |
| `primary` | `#2563EB` | Primary buttons, links, active navigation |
| `accent` | `#0EA5C9` | Secondary highlights and selected states |
| `border` | `#D9E1EA` | Borders, separators, table outlines |
| `text_primary` | `#172033` | Main text |
| `text_secondary` | `#64748B` | Supporting text and metadata |
| `success` | `#15803D` | Completed/success states |
| `warning` | `#B45309` | Warnings and partial results |
| `error` | `#B91C1C` | Failed/error states |

Do not scatter raw hex values through page files. Every new color must be
added to the central token map and have a semantic name.

### 5.3 Layout tokens

```text
sidebar_width: 232–248px
spacing scale: 8 / 12 / 16 / 24px
card radius: 10–14px
control radius: 8–10px
pill radius: full
content max width: fluid/wide
```

Use `st.container(border=True)` for cards and logical sections. Use
`st.container(horizontal=True)` for action/toolbars and responsive button
groups. Use `st.columns` only for small fixed grids of up to four columns.

Do not build the main layout from deeply nested custom HTML. If custom CSS is
needed, keep it in `ui/theme.py` and scope it to stable app-level classes.

### 5.4 Typography

- Preferred font: Inter.
- Fallback: system UI (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`,
  `sans-serif`).
- Body text should be readable at approximately 14px.
- Metadata/caption text may use 12–13px.
- Page titles should be visually prominent but compact.
- Use a monospace font only for technical logs, IDs, and raw diagnostics.

Recommended theme settings:

```toml
[theme]
base = "light"
primaryColor = "#2563EB"
backgroundColor = "#F6F8FB"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#172033"
borderColor = "#D9E1EA"
baseRadius = "10px"
buttonRadius = "8px"
showWidgetBorder = true
showSidebarBorder = true
font = "Inter:https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
headingFont = "Inter:https://fonts.googleapis.com/css2?family=Inter:wght@600;700&display=swap"

[theme.sidebar]
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F6F8FB"
textColor = "#172033"
borderColor = "#D9E1EA"
primaryColor = "#2563EB"
```

If the deployment environment cannot load the remote font, the UI must remain
usable with the system UI fallback.

### 5.5 Component rules

- Sidebar navigation width must remain between 232px and 248px on desktop.
- Active navigation uses `primary` or `accent` contrast, never a white-only
  active state that breaks the dark theme.
- Cards use `surface` with a subtle `border` outline; avoid heavy shadows.
- Primary action uses `primary`; secondary action uses a transparent or
  `surface` treatment with `border`.
- Progress indicators use `accent`.
- Status must be communicated by color plus text/icon, never by color alone.
- Tables must use readable column headers, horizontal scrolling where needed,
  and `st.dataframe(..., width="stretch")` rather than deprecated
  `use_container_width`.
- Use `st.badge` or semantic status callouts for job states.
- Use `st.status` for multi-step export progress and diagnostics.
- Keep advanced filters in an expander and avoid executing expensive work in
  a closed expander without an explicit action.
- Use `st.form` to submit filter groups in one action.
- Use `st.skeleton`, `st.empty`, or a bounded status area for loading states;
  do not leave blank layout gaps.

### 5.6 Responsive behavior

- At desktop width, show sidebar and main workspace side by side.
- At tablet width, filters wrap into one or two columns.
- At narrow width, action buttons stack vertically and tables scroll
  horizontally.
- Do not depend on fixed pixel widths for the main content area.
- The sidebar may collapse through Streamlit's native behavior, but its
  desktop design width remains 232–248px.

### 5.7 Visual validation

Every major UI phase must be checked in:

- dark desktop viewport;
- narrow/tablet viewport;
- long Vietnamese labels;
- loading, success, warning, and error states;
- empty filter/result states;
- large tables and download cards.

The visual review must verify contrast, alignment, spacing, responsive wrapping,
and that no raw token values are duplicated outside the design system.

## 6. Output compatibility contract

Every exporter must preserve:

- UTF-8 BOM encoding (`utf-8-sig`);
- exact column names and order;
- current Vietnamese/UTC conversion rules;
- current sorting;
- current empty-result behavior;
- current status mappings;
- current output row semantics.

Required schemas:

- Request Teacher: `CSV_COLUMNS` from `requestTC_fetch.py`;
- Survey: `BASE_COLUMNS` plus configured question IDs;
- Products: `DETAIL_COLUMNS` and `SUMMARY_COLUMNS`;
- Completion: `EXPORT_COLUMNS` from `completion_export.py`;
- Teacher Attendance: `EXPORT_COLUMNS` from `teacher_attendance_export.py`;
- Office Hours: `OUTPUT_COLUMNS` from `office_hours.py`;
- Class Observe: `EXPORT_COLUMNS` and `CSV_HEADERS` from `get_class.py`.

Do not manually recreate these lists in multiple locations. The exporter
module must remain the source of truth.

## 7. Streamlit UI requirements

Use one main `app.py` with a custom sidebar menu rather than seven unrelated
pages. This keeps authentication, job state, and artifact downloads stable.

Sidebar:

- logo;
- seven data modules;
- LMS status card;
- account email and expiry;
- check/refresh/logout controls.

Main area:

- page eyebrow;
- module title and description;
- status badge;
- primary filter card;
- advanced filter expander;
- load-filter button;
- class search and selected-class chips;
- preview/result summary;
- export button;
- progress bar;
- realtime log;
- download cards;
- activity history.

Use `st.form` for filter submission so ordinary widget changes do not trigger
expensive API requests. Use `st.session_state` for selections and loaded
options. Cache only safe metadata with bounded TTL; never cache secrets.

Use the current design system as visual input:

- teal primary palette;
- warm accent color;
- cool gray-blue application background;
- white raised cards;
- rounded corners;
- clear success/warning/error states;
- responsive layout for desktop and tablet.

## 8. Runtime job design

Streamlit reruns the script on interaction. Long-running exports must run in a
background worker and expose state through a job registry.

Each job record should contain:

```text
job_id
data_type
status
started_at
finished_at
parameters
progress
logs
output_artifacts
row_count
warning_count
error_message
```

Initial behavior: one active export per session. Use a queue for stdout/stderr
so existing exporter `print()` progress remains visible. Poll the job from the
UI at a short interval. If Community Cloud restarts or hibernates the app,
running jobs may be lost; the UI must explain that the user can rerun them.

Individual teacher-timesheet failures should preserve the current fallback
behavior but surface a warning count in the result panel.

## 9. Cloud storage and downloads

Do not depend on persistent local files on Community Cloud.

- Write to a temporary directory during a job.
- Read completed artifacts into bytes.
- Store only small artifact metadata in session state.
- Provide `st.download_button` for each output.
- Offer ZIP for multi-file exports.
- Clean temporary files after artifact bytes are captured.
- Do not promise that history survives Cloud restart.

If durable history or durable export storage is later required, add an external
database/object store in a separate phase. Do not introduce it into the MVP.

## 10. Dependency policy

Cloud `requirements.txt` should contain only packages required by the web app:

```text
streamlit
pandas
requests
python-dotenv
```

Pin versions after confirming the chosen Python version. Do not add PyQt6,
PyInstaller, or Playwright to the Cloud runtime unless a later design proves
they are necessary and compatible with Community Cloud.

Use `.streamlit/config.toml` for non-secret UI settings only. Secrets belong in
Community Cloud Advanced settings and in a local untracked
`.streamlit/secrets.toml` during development.

Official deployment references:

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app

## 11. Testing strategy

### Phase 0 contract fixtures

Before porting behavior, create redacted JSON fixtures from the current API
responses. Never commit real names, emails, tokens, IDs that are sensitive, or
real student/teacher data.

### Unit tests

Cover:

- date parsing and Vietnam timezone conversion;
- CSV/session/filter parsing;
- course/course-line/centre matching;
- pagination;
- status mappings;
- product detail and summary aggregation;
- completion counts;
- teacher attendance role and fallback logic;
- Class Observe exclusions;
- transient GraphQL retry logic;
- auth refresh and invalid-token paths.

### Golden compatibility tests

Run the same sanitized fixture through the old exporter and the new exporter,
then compare:

- row count;
- column list/order;
- every exported value;
- row ordering;
- date/time formatting;
- empty-result behavior.

### UI tests

Test at least:

- module navigation;
- token status display;
- loading filters;
- invalid date validation;
- empty result;
- successful export;
- failed export;
- download buttons;
- multi-file ZIP download;
- history display.

## 12. Implementation phases

### Phase 0 — Freeze current behavior

- Inventory all defaults and output schemas.
- Add/expand tests in the existing project where needed.
- Capture sanitized API fixtures.
- Record known fallback behavior.
- Confirm the current latest teacher-attendance retry changes are included.

Deliverable: compatibility baseline.

### Phase 1 — New project foundation

- Create package structure.
- Add `app.py`, `requirements.txt`, `.gitignore`, config, assets.
- Add settings loader supporting `.env` locally and `st.secrets` on Cloud.
- Add logging and error model.

Deliverable: empty Streamlit shell deploys successfully.

### Phase 2 — Auth and API client

- Port token validation and Firebase refresh logic.
- Implement Cloud Secrets auth.
- Implement shared requests session and retry policy.
- Add safe error sanitization.

Deliverable: private Cloud app can verify and refresh the configured LMS
account without Playwright.

### Phase 3 — Exporter migration

Port each exporter with minimal changes and compatibility tests. Recommended
order:

1. Teacher Attendance
2. Completion
3. Products
4. Request Teacher
5. Office Hours
6. Class Observe
7. Survey

Deliverable: every exporter can run from Python service calls without PyQt.

### Phase 4 — Job manager and artifacts

- Add background jobs.
- Capture logs and progress.
- Create temporary artifacts.
- Add CSV/ZIP download objects.

Deliverable: long exports do not block the Streamlit UI.

### Phase 5 — UI implementation

- Build shell, sidebar, auth panel, common filters, result cards, logs, and
  history.
- Add each data module using the same form pattern.
- Apply the design system.

Deliverable: complete user-facing app locally.

### Phase 6 — Compatibility and performance

- Run golden tests.
- Test long date ranges.
- Test pagination and empty data.
- Test backend connection failures.
- Reduce concurrency where Cloud resources require it.

Deliverable: release candidate with no known output mismatch.

### Phase 7 — Community Cloud deployment

- Push to a private GitHub repository.
- Deploy `app.py` through `share.streamlit.io`.
- Choose the same Python version used locally.
- Paste secrets in Advanced settings.
- Set the app private and invite approved viewers.
- Validate every export from the deployed URL.

Deliverable: usable private `streamlit.app` deployment without Docker.

## 13. Definition of done

The project is complete when:

- all seven modules work;
- all existing CSV contracts pass golden tests;
- the app runs without PyQt6 or Docker;
- Community Cloud deploys from `requirements.txt`;
- LMS auth works through Cloud Secrets;
- no secret is committed or displayed;
- long jobs show progress and logs;
- exports can be downloaded directly;
- Products supports detail, summary, and ZIP downloads;
- retry/fallback warnings are visible;
- private viewer access is configured;
- README documents local run, secrets setup, and deployment.

## 14. Current status

Implementation v1 is in place:

- All seven legacy exporter modules are vendored while preserving their CSV schemas.
- `AuthService`, `JobManager`, CSV/ZIP artifact downloads, LMS catalog filters, and
  the Clean Enterprise Streamlit shell are implemented.
- Community Cloud/no-Docker setup is included through `requirements.txt`,
  `.streamlit/config.toml`, and `.env.example`.
- `py_compile`, full legacy-module imports, schema checks, and a job-manager smoke
  test pass locally.

Before production, add HTTP/GraphQL fixture tests, complete advanced per-module
filters, add teacher-attendance-specific observability, and manually validate all
exports on Community Cloud with real Secrets.
