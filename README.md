### Now Live on:
**https://posit-connect.am.lilly.com/content/703605bb-fc13-40fc-b0af-6cbe236d624d**

## Dev Notes

`beta` branch:
> - deploy testing and everything. will be removed once final version out. 

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
>

`archive` branch:
> - archive feature to view curated data set from server-side;
> - check updates feature to compare saved ones with most-up-to-date ones from ct.gov;
> - click NCT number to edit the specific trial based on user's needs;
> - keep user saved data per session. 
