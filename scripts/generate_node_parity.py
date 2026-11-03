"""Developer-only parity fixture generator. The Node application never calls Python."""
import json
import sys
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from grantiq.app.schemas.domain import OrganizationProfile, GrantRecord
from grantiq.app.services.scoring import score_grant
class Embedder:
    backend_name='fixture'
    def similarity(self,*args):return .8
p=OrganizationProfile(name='Example charity',mission='Vision care and preventive health for children',programs=['vision screening'],service_locations=['Duval County, Florida'],populations_served=['children'],funding_interests=['eye health'])
base=dict(source='Test',source_id='1',source_url='https://example.org/grant',grant_title='Vision care for children',funder_name='Example Foundation',description='Vision screening and preventive eye health',eligibility_text='501(c)(3) nonprofit organizations are eligible.',applicant_types=['501(c)(3) nonprofits'],geographic_restrictions=['Florida'],geography_scope='state',populations_served=['children'],program_areas=['vision screening'],award_min=5000,award_max=10000,deadline='2099-12-31',grant_status='posted')
variants=[{},dict(applicant_types=['State governments only']),dict(geographic_restrictions=['Orange County, Florida']),dict(geographic_restrictions=['Duval County, Florida']),dict(geographic_restrictions=[],geography_scope='unknown'),dict(geography_scope='national'),dict(geography_scope='national',eligibility_text='Available nationally excluding Florida'),dict(deadline='2000-01-01'),dict(grant_status='forecasted'),dict(deadline=None,deadline_text='rolling'),dict(deadline=None),dict(award_min=None,award_max=None),dict(award_min=0,award_max=0),dict(award_min=None,award_max=2000),dict(invitation_only=True),dict(matching_funds_required=True),dict(fiscal_sponsor_required=True),dict(existing_relationship_required=True),dict(budget_min=100000),dict(eligibility_text='Only children may be served; nonprofits may apply'),dict(eligibility_text='Nonprofits are not eligible'),dict(applicant_types=[]),dict(program_areas=[],categories=[]),dict(populations_served=[]),dict(grant_status='unknown'),dict(open_date='2099-01-01'),dict(deadline='2026-10-23'),dict(deadline='2026-11-10'),dict(deadline='2026-11-30'),dict(past_giving=[dict(recipient='Charity',source_url='https://example.org/evidence',purpose='Vision care for children')])]
fixtures=[]
for i,v in enumerate(variants):
 g=GrantRecord(**{**base,**v});a=score_grant(g,p,today=date(2026,10,21),embedder=Embedder())
 fixtures.append(dict(name=f'Python rule case {i+1}',profile=p.model_dump(mode='json'),record=g.model_dump(mode='json'),fit_score=a.fit_score,confidence_score=a.confidence_score,eligibility_status=a.eligibility_status,points={c.key:c.points for c in a.components}))
target=ROOT/'node/tests/fixtures/python-parity.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(fixtures,indent=2))
print(f'Wrote {len(fixtures)} synthetic Python reference cases.')
