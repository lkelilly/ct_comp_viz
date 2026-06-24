## To Run It Locally

1. Clone the repo
   ```bash
   git clone <repo-url>
   cd ct_comp_viz
   ```

2. Create a virtual environment and install dependencies
   ```bash
   python -m venv .venv

   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. Run the app
   ```bash
   shiny run app.py
   ```
   Then open `http://127.0.0.1:8000` in your browser.

### Dev Notes

`indication-rule` branch: 
Changes from the initial version: 
> - Using a more complex logic of indication handling with overrinding rules than just extracting the condition and matching with synonym. (added) 
> - Add acronym search from title rule: 
>     - all caps + parenthesis (more tests needed) 
> - Compound mutate from the user's input or the primary intervention (the first, ignore placebo) 
>     - placebo handling logic pending 
> - New outcome columns to keep (added)
> - Added participation criteria. 
>     - split the eligibility and exclusion. 

`viz` branch:
> - fix the upload data logic in:
>     - compound: ignore placebo, display the most general term
>     - indication: splitting rule include minor cases where no whitespace around conditions. 
> - add viz

`pub` branch:
> - add PubMed API, match NCT number, filter for primary result paper.
> - fix date rendering issue with _itables_ package. 
> - pub selection logic:
>     - keep all pubs from main journals;
>     - filter for papers after completion date (2 months grace period);
>     - drop post-hoc or secondary analysis papers;
>     - rank by citation count, if not papers in main journals, keep 2 at maximum. 