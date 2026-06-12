`indication rule` branch: 
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