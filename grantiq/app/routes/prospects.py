from datetime import date
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from ..config import ROOT
from ..models import ResearchProspect, SearchCursor
from ..security import validate_csrf
from ..services.research_context import DISPOSITIONS, keyword_library, keyword_plan, existing_funders
from ..services.repository import get_profile
from .web import render, session_for

router=APIRouter()

@router.get('/research')
def research(request:Request):
    with session_for(request) as session:
        prospects=session.scalars(select(ResearchProspect).order_by(ResearchProspect.id)).all()
        cursor=session.get(SearchCursor,1)
        terms,_,pool_size=keyword_plan(get_profile(session),cursor.position if cursor else 0)
        library=keyword_library()
        return render(request,'research.html',session,prospects=prospects,library=library,
            funder_register=existing_funders(),
            dispositions=DISPOSITIONS,today=date.today(),next_terms=terms,pool_size=pool_size,
            available_documents={key for key, name in {'ranking':'Grant Ranking.docx.pdf','keywords':'Grant Search Keywords.docx.pdf'}.items() if (ROOT/'references'/name).is_file()},
            unique_terms=len({t.casefold() for group in library['groups'] for t in group['terms']}))

@router.post('/research/{prospect_id}')
async def update_prospect(request:Request,prospect_id:str):
    form=await request.form()
    validate_csrf(request,form)
    if form.get('disposition') not in DISPOSITIONS:
        raise HTTPException(422,'Choose a supported staff decision.')
    try:
        review_on=date.fromisoformat(form['review_on']) if form.get('review_on') else None
    except ValueError:
        raise HTTPException(422,'Enter a valid review date.')
    notes=str(form.get('team_notes','')).strip()
    if len(notes)>15000:
        raise HTTPException(422,'Team notes must be no longer than 15,000 characters.')
    with session_for(request) as session:
        row=session.get(ResearchProspect,prospect_id)
        if row is None:
            raise HTTPException(404,'Research prospect not found.')
        row.disposition,row.review_on,row.team_notes=form['disposition'],review_on,notes
        session.commit()
    return RedirectResponse(f'/research?notice=Staff+decision+saved.+Original+document+notes+are+preserved.#{prospect_id}',status_code=303)

@router.get('/research-documents/{document}')
def original_document(document:str):
    files={'keywords':'Grant Search Keywords.docx.pdf','ranking':'Grant Ranking.docx.pdf'}
    if document not in files:
        raise HTTPException(404,'Document not found.')
    if not (ROOT/'references'/files[document]).is_file():
        raise HTTPException(404,'This internal document is not installed.')
    return FileResponse(ROOT/'references'/files[document],media_type='application/pdf',filename=files[document])
