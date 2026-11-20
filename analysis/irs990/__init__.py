"""Find candidate funders in public IRS Form 990-PF filings.

Private foundations file a 990-PF each year listing every grant they paid: the
recipient, the amount, and the stated purpose. Those filings are public. This
package narrows the national dataset down to Northeast Florida foundations and
reads their grant lists, so staff can see which nearby funders already support
work like this organization's.

Offline research only: nothing here touches the database or the web app.
"""
