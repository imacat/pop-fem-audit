=======================================
Tools for A Feminist Audit of Pop Music
=======================================


Description
===========

This is a collection of supporting tools for the conference paper "流行音樂中「女性力量」語彙的挪用與污染——以 Billboard Year-End Hot 100（2016–2025）為例的內容分析".


Installation
============

Use ``pip`` to install these tools.

::

    % pip install .

This will install the ``pop-fem-audit-tools`` script in the Python environment.


Usage
=====

::

    % pop-fem-audit-tools {command} [options] [arguments]

Runs a specific tool command, where "command" can be:


build-db
--------

Initialize or rebuild the database from the CSV Billboard ranking table, parse songs and its artists, and output song and artist lists for references.  Check ``pop-fem-audit-tools build-db -h`` for complete instructions on its usage.


fetch-artists
-------------

Fetch artist data from Wikidata, for ``build-db`` to merge the fetched data into the database.  Check ``pop-fem-audit-tools fetch-artists -h`` for complete instructions on its usage.


fetch-lyrics
------------

Fetch lyrics, for ``build-db`` to merge the fetched lyrics into the database.  Lyrics are not committed into the repository due to copyright issue.  Check ``pop-fem-audit-tools fetch-lyrics -h`` for complete instructions on its usage.


export-llm-input
----------------

Export song data for ``run-llm`` to talk to LLM.  Check ``pop-fem-audit-tools export-llm-input -h`` for complete instructions on its usage.


run-llm
-------

A general command that runs specific LLM instructions with the Anthropic API.  The API key must be present in the ``.env`` file in the working directory.  Check ``pop-fem-audit-tools run-llm -h`` for complete instructions on its usage.


cluster-keywords
----------------

Deterministically build the coding vocabulary from the two tagging runs' archives, by pooling their keywords per the project's handoff contract and then sentence-embedding and clustering them.  Check ``pop-fem-audit-tools cluster-keywords -h`` for complete instructions on its usage.


compare-codings
---------------

Compare the two coding runs' archives and export the per-song disagreements, for the arbitration step to rule on.  The keywords both runs assigned are settled by the comparison itself; only the keywords assigned by exactly one run are exported, each with the quotes the assigning run gave as evidence.  Check ``pop-fem-audit-tools compare-codings -h`` for complete instructions on its usage.


Copyright
=========

 Copyright (c) 2026 imacat.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.


Authors
=======

| imacat
| imacat@mail.imacat.idv.tw
| 2026/7/31
