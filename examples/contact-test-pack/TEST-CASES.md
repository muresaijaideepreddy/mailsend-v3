# Contact matching test checklist

Import google-contacts-20.csv into Google Contacts using the connected executive account. The file contains only names and email addresses. All addresses are synthetic example.test addresses: use these for lookup tests, not delivery.

Google Contacts: Import > Select file > choose the CSV > Import. Import once to avoid duplicate test records. Existing contacts can add extra suggestions.

In MailSend open a saved draft > Find recipient in Google contacts. Search the names below. Do not assign a fictional contact to a real business draft; use a disposable test draft for selection testing.

| Search | Case | Observed locally with these 20 contacts |
|---|---|---|
| Chao Wang | Exact name | Chao Wang (mailsend.test01@example.test, 100%) |
| Chloe Bennett | Exact name | Chloe Bennett (mailsend.test02@example.test, 100%) |
| Chris Morgan | Exact name | Chris Morgan (mailsend.test03@example.test, 100%) |
| Chris Patel | Exact name | Chris Patel (mailsend.test04@example.test, 100%) |
| Karina Lopez | Exact name | Karina Lopez (mailsend.test05@example.test, 100%) |
| Jeff Carter | Exact name | Jeff Carter (mailsend.test06@example.test, 100%) |
| Tim Wilson | Exact name | Tim Wilson (mailsend.test07@example.test, 100%) |
| Gideon Brooks | Exact name | Gideon Brooks (mailsend.test08@example.test, 100%) |
| DeForest Reed | Exact name | DeForest Reed (mailsend.test09@example.test, 100%) |
| Brent Davis | Exact name | Brent Davis (mailsend.test10@example.test, 100%) |
| Ankit Sharma | Exact name | Ankit Sharma (mailsend.test11@example.test, 100%) |
| Matt Evans | Exact name | Matt Evans (mailsend.test12@example.test, 100%) |
| Charles Turner | Exact name | Charles Turner (mailsend.test13@example.test, 100%) |
| Udith Perera | Exact name | Udith Perera (mailsend.test14@example.test, 100%) |
| Rakesh Kumar | Exact name | Rakesh Kumar (mailsend.test15@example.test, 100%) |
| Jaideep Reddy | Exact name | Jaideep Reddy (mailsend.test16@example.test, 100%) |
| JosÃ© GarcÃ­a | Exact name | JosÃ© GarcÃ­a (mailsend.test17@example.test, 100%) |
| Anne-Marie Lee | Exact name | Anne-Marie Lee (mailsend.test18@example.test, 100%) |
| John Smith | Exact name | John Smith (mailsend.test19@example.test, 100%); John Smith (mailsend.test20@example.test, 100%) |
| John Smith | Exact name | John Smith (mailsend.test19@example.test, 100%); John Smith (mailsend.test20@example.test, 100%) |
| Chloee Bennett | Typo | Chloe Bennett (mailsend.test02@example.test, 96%) |
| Jaidep Reddy | Typo | Jaideep Reddy (mailsend.test16@example.test, 96%) |
| Jaidep | First-name typo | Jaideep Reddy (mailsend.test16@example.test, 83%) |
| Jose Garcia | Accent | JosÃ© GarcÃ­a (mailsend.test17@example.test, 78%) |
| Reddy Jaideep | Reordered name | Jaideep Reddy (mailsend.test16@example.test, 100%) |
| Dr. Chao Wang | Title | Chao Wang (mailsend.test01@example.test, 100%) |
| Anne Marie Lee | Punctuation | Anne-Marie Lee (mailsend.test18@example.test, 100%) |
| Chris | Two people; review both | Chris Morgan (mailsend.test03@example.test, 90%); Chris Patel (mailsend.test04@example.test, 90%) |
| John Smith | Same name; review both | John Smith (mailsend.test19@example.test, 100%); John Smith (mailsend.test20@example.test, 100%) |
| X | No match | No match |
| Unknown Person Zzz | No match | No match |
| Team | No match | No match |

Local fixture checks: 32/32 passed. Google import and live lookup of this pack have not yet been performed. Scores measure spelling similarity, not proof of identity.

## Selection checks

1. Exact match: choose a contact on a disposable draft; confirm only the selected recipient field changes.
2. Ambiguous name: search Chris or John Smith; choose the intended email explicitly.
3. No match: leave the recipient blank and verify sending stays blocked.
4. Stale choice: edit the draft in another tab, then try an old suggestion; it should require another search.
5. Worker account: verify the executive contact lookup is unavailable.
6. Confirm no email is sent by searching or selecting a contact.