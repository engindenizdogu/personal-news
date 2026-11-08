# Graph v0: statistics

Entities kept if mentioned by at least 1 item(s).

| Nodes | Count |
|---|---|
| item | 45 |
| source | 9 |
| entity | 726 |
| **total** | **780** |

| Edges (one direction) | Count |
|---|---|
| item → source (`from`) | 45 |
| item → entity (`mentions`) | 857 |

| Entities by type | Count |
| ---------------- | ----- |
| location         | 64    |
| organization     | 136   |
| person           | 276   |
| product          | 250   |

| Degree            | min | median | mean  | max |
| ----------------- | --- | ------ | ----- | --- |
| items per entity  | 1   | 1.0    | 1.18  | 10  |
| entities per item | 0   | 12     | 19.04 | 185 |

- Entities mentioned by one item only: 654 of 726 (90%); entities seen in more than one source: 25
- Items without entities: 1
- Item pairs sharing at least one entity: 164 (107 across sources); items with such a link: 39 of 45; largest linked group: 37 items
- Whole graph: 2 connected component(s), density 0.00297

| Top entities | Type | Items | Sources |
|---|---|---|---|
| United States | location | 10 | 5 |
| OpenAI | organization | 9 | 3 |
| Stripe | organization | 7 | 2 |
| Anthropic | organization | 6 | 2 |
| Cloudflare | organization | 6 | 2 |
| Meta | organization | 6 | 4 |
| Google | organization | 5 | 2 |
| United Kingdom | location | 4 | 3 |
| Washington | location | 4 | 1 |
| Nature | organization | 4 | 1 |
| Republican Party | organization | 4 | 1 |
| Donald Trump | person | 4 | 1 |
| The Pulse | product | 4 | 1 |
| X | product | 4 | 2 |
| China | location | 3 | 2 |

| Items per source   | Count |
| ------------------ | ----- |
| bbc_us_canada      | 5     |
| cloudflare         | 5     |
| coding_horror      | 5     |
| deepmind           | 5     |
| hackernoon         | 5     |
| nature             | 5     |
| openai             | 5     |
| pragmatic_engineer | 5     |
| stripe             | 5     |
