# Web Scraping Framework: Handling SSR, CSR, and XHR

This document explains the technical approach used in this project to handle different types of web content: **Server-Side Rendered (SSR)**, **Client-Side Rendered (CSR)**, and **XHR (AJAX) loaded** content.

The framework employs a **Hybrid Strategy** that dynamically switches between lightweight HTTP requests and heavy-duty browser automation depending on the target content's nature.

---

## 1. High-Level Architecture

The process relies on orchestrating specialized modules. Here is the flow for any given URL:

1.  **`crawler.py`**: Determines *what* to crawl next (BFS logic).
2.  **`scraper.py`**: Determines *how* to fetch the content (Static vs. Dynamic).
3.  **`parser.py`**: Extracts data from the resulting HTML (Strategy agnostic).

---

## 2. Handling Server-Side Rendering (SSR)

**What it is:** The server initiates the request and sends a fully populated HTML document.
**Example:** Wikipedia, standard blogs, legacy sites.

### procedural Flow

1.  **Control**: `crawler.ProcessUrl` calls `scraper.scrape_page()`.
2.  **Fetching (`scraper.py`)**:
    -   The `fetch_static_content()` function is invoked.
    -   It uses the `requests` library to send a standard HTTP GET request.
    -   **Benefit**: Extremely fast, low resource usage, no browser overhead.
3.  **Parsing (`parser.py`)**:
    -   The raw HTML text response is passed to `BeautifulSoup`.
    -   Data (H1, P, Links) is extracted directly from this static HTML tree.

---

## 3. Handling Client-Side Rendering (CSR) & XHR

**What it is:** The server sends a skeletal HTML shell. JavaScript then executes in the browser, making API calls (XHR/Fetch) to get data and populate the DOM.
**Example:** React, Vue, Angular apps, Infinite scrolling sites, Single Page Applications (SPAs).

### Procedural Flow

1.  **Control**: If `scraper.py` is configured for dynamic content (or fallback is triggered), it switches strategy.
2.  **Browser Setup (`driver_manager.py`)**:
    -   Initializes a Headless Chrome instance.
    -   Configures options (anti-detection, window size) to mimic a real user.
3.  **Fetching & Rendering (`scraper.py`)**:
    -   The `fetch_dynamic_content()` function is invoked.
    -   **Navigation**: `driver.get(url)` loads the page.
    -   **Execution**: The browser executes all embedded JavaScript.
    -   **XHR Handling**: The browser automatically issues background XHR requests to fetch data.
    -   **Waiting**: The script implicitly waits (via Selenium's connection logic) or explicitly sleeps (via `random_delay`) to ensure the DOM is fully hydrated by the JavaScript.
    -   **Extraction**: It captures `driver.page_source`. This is the *final* computed HTML after all JS/XHR has finished running.
4.  **Parsing (`parser.py`)**:
    -   This populated HTML (which looks just like SSR HTML to the parser) is passed to `BeautifulSoup`.
    -   The parser extracts the data that was dynamically inserted into the DOM.

---

## 4. Module-Wise Responsibility Breakdown

### `scraper.py` (The Strategy Engine)
This is the core module that bridges the gap between SSR and CSR.
-   **Function `scrape_page(url)`**: Orchestrates the decision.
-   **Function `fetch_static_content(url)`**: Handles **SSR**. Uses `requests`.
-   **Function `fetch_dynamic_content(url)`**: Handles **CSR/XHR**. Uses `selenium`. It renders the JavaScript and waits for XHRs to complete their DOM updates before capturing the HTML.

### `driver_manager.py` (The CSR Infrastructure)
-   Manages the lifecycle of the Selenium WebDriver.
-   Ensures a reliable browser environment is available for **CSR** tasks.

### `parser.py` (The Agnostic Extractor)
-   It does not know if the HTML came from SSR or CSR.
-   It receives standard HTML string and uses `BeautifulSoup` to create a DOM tree.
-   **Key Insight**: By converting CSR pages to static HTML (via `driver.page_source`), we reuse the exact same parsing logic for both types of sites.

### `crawler.py` (The Orchestrator)
-   Manages the frontier (queue) of URLs to visit.
-   Ensures recursion depth (`MAX_DEPTH`) is respected.
-   It treats SSR and CSR URLs identically in terms of queue management.

### `logger.py` & `utils.py`
-   **`logger.py`**: Records structured JSON logs. Crucial for debugging whether dynamic content was successfully loaded (e.g., if a title is missing in static scrape but present in dynamic).
-   **`utils.py`**: Provides `get_random_user_agent()` to ensure both Requests and Selenium mimic legitimate browser traffic, preventing blocking on XHR calls.
