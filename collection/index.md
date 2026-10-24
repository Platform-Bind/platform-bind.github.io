---
title: Curated collection
---

# Curated collection

The Platform Bind collection is organised into the subcollections below.

{% assign subcollections = site.pages | where: "layout", "subcollection" | sort: "order" %}
<ul class="subcollections">
  {% for sub in subcollections %}
  <li>
    <a href="{{ sub.url | relative_url }}">{{ sub.title }}</a>
    {% if sub.summary %}<p>{{ sub.summary }}</p>{% endif %}
  </li>
  {% endfor %}
</ul>
