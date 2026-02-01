# CiteFix

Citation formatting, DOI resolution, and validation for Word documents.

## Features

- **Citation Formatting**: Reformat references to APA, MLA, Chicago, Vancouver, IEEE, or custom styles
- **DOI Resolution**: Automatically look up and add DOI URLs via CrossRef API
- **Validation**: Check that all in-text citations have matching references (and vice versa)
- **Example-Based Learning**: Provide example citations to learn your desired format

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd CiteFix

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

## Quick Start

```bash
# Start the web server
uvicorn app.main:app --reload

# Open http://localhost:8000 in your browser
```

## Usage

1. Upload a Word document (.docx) containing citations and a references section
2. Select a citation style or provide example citations
3. Enable/disable DOI lookup and validation
4. Click "Process Document"
5. Review the validation report
6. Download the processed document

## API Endpoints

- `POST /api/process` - Process a document (format, DOI lookup, validate)
- `POST /api/validate` - Validate citations only
- `GET /api/download/{id}` - Download processed document
- `GET /api/styles` - List available citation styles

## Supported Citation Formats

**In-text citations:**
- Author-year: `(Smith, 2020)`, `(Smith & Jones, 2020)`, `(Smith et al., 2020)`
- Numeric: `[1]`, `[1, 2]`, `[1-3]`

**Reference styles:**
- APA (7th Edition)
- MLA (9th Edition)
- Chicago (Author-Date)
- Harvard
- Vancouver
- IEEE
- Custom (learned from examples)

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=app

# Format code (if ruff is installed)
ruff format app/ tests/
```

## License

MIT
