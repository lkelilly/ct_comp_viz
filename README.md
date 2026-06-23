`pub` branch:
> add PubMed API, match NCT number, filter for primary result paper.
> fix date rendering issue with _itables_ package. 
> publication matching/filering logic:
> - extract PMID from _ct.gov_, send to _PubMed_ API. 
> - fetch from PMID, match NCT number with _[si]_, title, or abstract. 
> - trying to find the primary result paper display.
>     - logic to be put there. 
> - keep papers from important journals and rank by citation number, keep top 3. 