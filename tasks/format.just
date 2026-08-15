# run format tasks
[group('format')]
format: format-import format-source

# format code import
[group('format')]
format-import:
    uv run ruff check --select=I --fix {{SOURCES}} {{TESTS}} {{EXAMPLES}}

# format code source (DOCS covers python blocks inside markdown)
[group('format')]
format-source:
    uv run ruff format {{SOURCES}} {{TESTS}} {{EXAMPLES}} {{DOCS}}
