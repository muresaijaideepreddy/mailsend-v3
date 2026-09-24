# Integrated upload test results

Tested using the connected Google account and the synthetic contact-matching-20-emails.pdf. All 20 contacts were available. The browser created drafts 45-64. No emails were sent.

| Case | Greeting name | Expected and verified To | Outcome |
|---|---|---|---|
| 01 | Chao Wang | mailsend.test01@example.test | Exact match filled |
| 02 | Chloe Bennett | mailsend.test02@example.test | Exact match filled |
| 03 | Karina Lopez | mailsend.test05@example.test | Exact match filled |
| 04 | Jeff Carter | mailsend.test06@example.test | Exact match filled |
| 05 | Tim Wilson | mailsend.test07@example.test | Exact match filled |
| 06 | Gideon Brooks | mailsend.test08@example.test | Exact match filled |
| 07 | DeForest Reed | mailsend.test09@example.test | Exact match filled |
| 08 | Brent Davis | mailsend.test10@example.test | Exact match filled |
| 09 | Ankit Sharma | mailsend.test11@example.test | Exact match filled |
| 10 | Matt Evans | mailsend.test12@example.test | Exact match filled |
| 11 | Charles Turner | mailsend.test13@example.test | Exact match filled |
| 12 | Udith Perera | mailsend.test14@example.test | Exact match filled |
| 13 | Jaidep Reddy | (blank) | Blank for review |
| 14 | Chris | (blank) | Blank for review |
| 15 | John Smith | (blank) | Blank for review |
| 16 | Unknown Person Zzz | (blank) | Blank for review |
| 17 | X | (blank) | Blank for review |
| 18 | Jeff Carter | preserved@example.test | Existing address preserved |
| 19 | Jose Garcia | mailsend.test17@example.test | Exact match filled |
| 20 | Rakesh Kumar | (blank) | Blank for review |

All subjects, bodies, dates, To, CC and BCC values matched expected results. Thirteen automatic matches were audited. Six unresolved drafts were blocked from sending.

Open Contact import test 13 to see the typo suggestion, test 14 for two people named Chris, test 15 for duplicate John Smith contacts, test 18 for an existing email, test 19 for accent normalization, or test 20 for unresolved CC review.

The PDF has already been uploaded once for testing. Uploading it again intentionally creates another batch.