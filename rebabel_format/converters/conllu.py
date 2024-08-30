#!/usr/bin/env python3

from .reader import LineReader, ReaderError
from .writer import Writer

class ConnluReader(LineReader):
    '''
    Units imported:

    - sentence

    Each sentence is imported as a top-level unit. Any comment lines which
    contain `=` will be imported as string features in the `UD` tier.

    - word, token

    Each line of the sentence will be added as either a word node or a token
    node. The parent will be set to the sentence and relations will be added
    from any overt word to the containing token.

    The non-empty single-valued columns will be imported in the `UD` tier with
    the names `id`, `form`, `lemma`, `upos`, `xpos`, `head`, and `deprel`.
    All of these are string features except `head`, which is a reference feature.
    Words whose head is `0` will have `UD:head` unset.

    The features and miscelaneous columns will be imported as string features
    in the tiers `UD/FEATS` and `UD/MISC`, respectively.
    An exception is made for `UD/MISC:SpaceAfter`, which is imported as a boolean
    feature.

    - UD-edep

    Enhanced dependencies are imported as `UD-edep` nodes. Their parent is the
    sentence and they have reference features `UD:parent` and `UD:child` and
    a string feature `UD:deprel`.
    '''

    identifier = 'conllu'
    short_name = 'CoNNL-U'
    long_name = 'Universal Dependencies CoNNL-U format'
    format_specification = 'https://universaldependencies.org/format'

    block_name = 'sentence'

    def reset(self):
        self.word_idx = 0
        self.token_idx = 0
        self.edep_count = 0

    def end(self):
        if self.id_seq:
            self.set_type('sentence', 'sentence')
            self.set_feature('sentence', 'meta', 'index', 'int',
                             self.block_count)
        super().end()

    def process_line(self, line):
        if not line:
            return

        if line[0] == '#':
            if '=' in line:
                k, v = line[1:].split('=', 1)
                self.set_feature('sentence', 'UD', k.strip(), 'str', v.strip())
            return

        columns = line.strip().split('\t')
        if len(columns) != 10:
            self.error(f'Expected 10 columns, found {len(columns)}.')

        name = columns[0]
        is_token = '-' in name
        self.set_type(name, 'token' if is_token else 'word')
        self.set_parent(name, 'sentence')
        self.set_feature(name, 'UD', 'id', 'str', name)
        if is_token:
            self.token_idx += 1
            self.set_feature(name, 'meta', 'index', 'int', self.token_idx)
            a, b = name.split('-', 1)
            if a.isdigit() and b.isdigit():
                for ch in range(int(a), int(b)+1):
                    self.add_relation(str(ch), name)
        else:
            self.word_idx += 1
            self.set_feature(name, 'meta', 'index', 'int', self.word_idx)
            self.set_feature(name, 'UD', 'null', 'bool', '.' in name)

        for group, val in [('UD/FEATS', columns[5]), ('UD/MISC', columns[9])]:
            if val == '_':
                continue
            for pair in val.split('|'):
                if '=' not in pair:
                    self.error(f"Invalid key-value pair '{pair}'.")
                k, v = pair.split('=', 1)
                typ = 'str'
                if k == 'SpaceAfter':
                    typ = 'bool'
                    v = (v != 'No')
                self.set_feature(name, group, k, typ, v)

        col_names = [('form', 1), ('lemma', 2), ('upos', 3), ('xpos', 4),
                     ('head', 6), ('deprel', 7)]
        for feat, col in col_names:
            if columns[col] != '_':
                typ = 'str'
                if feat == 'head':
                    if columns[col] == '0':
                        continue
                    typ = 'ref'
                self.set_feature(name, 'UD', feat, typ, columns[col])

        if columns[8] != '_':
            for pair in columns[8].split('|'):
                if ':' not in pair:
                    self.error(f"Invalid dependency specifier '{pair}'.")
                self.edep_count += 1
                ename = f'\t{self.edep_count}'
                self.set_type(ename, 'UD-edep')
                self.set_parent(ename, 'sentence')
                head, rel = pair.split(':', 1)
                self.set_feature(ename, 'UD', 'parent', 'ref', h)
                self.set_feature(ename, 'UD', 'child', 'ref', name)
                self.set_feature(ename, 'UD', 'deprel', 'str', rel)

class ConlluWriter(Writer):
    identifier = 'conllu'

    def write(self, fout):
        # TODO: sorting (meta:index?)
        feat_dict = self.all_feats_from_tiers(['UD', 'UD/FEATS', 'UD/MISC'])
        feat_list = list(feat_dict.keys())
        sent_id = None
        null = None
        for k, v in feat_dict.items():
            if v == ('UD', 'sent_id', 'str') or v == ('UD', 'sent_id', 'int'):
                sent_id = k
            elif v == ('UD', 'null', 'bool'):
                null = k
        for sid, sfeats in self.iter_units('sentence', feat_list):
            si = sfeats.get(sent_id, sid)
            fout.write(f'# sent_id = {si}\n')
            for k, v in sfeats.items():
                if k == sent_id:
                    continue
                tier, feat, typ = feat_dict[k]
                if tier == 'UD':
                    fout.write(f'# {feat} = {v}\n')
            words = []
            id2idx = {}
            idx1 = 0
            idx2 = 0
            heads = [] # [(words index, id), ...]
            for wid, wfeats in self.iter_units('word', feat_list, sid):
                widx = ''
                if wfeats.get(null, False) == True:
                    idx2 += 1
                    widx = f'{idx1}:{idx2}'
                else:
                    idx1 += 1
                    idx2 = 0
                    widx = str(idx1)
                id2idx[wid] = widx
                row = [widx] + ['_']*9
                FEAT = []
                MISC = []
                for i, v in wfeats.items():
                    tier, feat, typ = feat_dict[i]
                    if tier == 'UD/FEATS':
                        FEAT.append(f'{feat}={v}')
                    elif tier == 'UD/MISC':
                        if feat == 'SpaceAfter' and typ == 'bool':
                            if not v or v == b'0':
                                v = 'No'
                            else:
                                v = 'Yes'
                        MISC.append(f'{feat}={v}')
                    elif tier == 'UD':
                        if feat == 'form':
                            row[1] = v
                        elif feat == 'lemma':
                            row[2] = v
                        elif feat == 'upos':
                            row[3] = v
                        elif feat == 'xpos':
                            row[4] = v
                        elif feat == 'deprel':
                            row[7] = v
                        elif feat == 'head':
                            heads.append((len(words), v))
                if FEAT:
                    row[5] = '|'.join(sorted(FEAT))
                if MISC:
                    row[9] = '|'.join(sorted(MISC))
                words.append(row)
            for i, h in heads:
                if h in id2idx:
                    words[i][6] = id2idx[h]
            # TODO: tokens
            for row in words:
                if row[6] == '_' and row[7] == 'root':
                    row[6] = '0'
            fout.write('\n'.join('\t'.join(row) for row in words) + '\n\n')
