"""
Define utility classes for attention.
"""
import logging
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

class PositionalEncoder:
    def __init__(self, emb_dim):
        self.emb_dim = emb_dim

    def __call__(self, length):
        dim_indices = np.arange(self.emb_dim)
        x = np.outer(
            np.arange(length),
            10000 ** (-2 * np.floor(dim_indices / 2) / self.emb_dim),
        )
        positional_encoding = np.sin(x + np.pi / 2 * dim_indices % 2)
        positional_encoding = positional_encoding.astype(np.float32)

        return positional_encoding

class SingleDotProductAttention:
    def __init__(self, forward_masked=False):
        self.forward_masked = forward_masked

    def __call__(self, query, key, value, key_mask=None):
        scores = torch.einsum('imk,jmk->imj', query, key)
        scores /= key.shape[2] ** 0.5
        if key_mask is not None:
            scores -= key_mask.float().transpose(1, 0) * 1e18
        if self.forward_masked and query.shape[1] is not None:
            scores -= torch.unsqueeze(
                torch.triu(torch.ones((query.shape[0], query.shape[0]))), 1
            ) * 1e18
        attentions = F.softmax(scores, dim=2)
        outputs = torch.einsum('imj,jmk->imk', attentions, value)

        return outputs

class MultiHeadAttention(nn.Module):
    def __init__(self, input_dim, hidden_dim, head_count, forward_masked=False):
        super(MultiHeadAttention, self).__init__()

        assert input_dim % head_count == 0, \
            'The argument model_dim should be divided by the argument head_count.'

        self.head_count = head_count

        self.query_dense_layers = []
        self.key_dense_layers = []
        self.value_dense_layers = []
        self.dot_product_attentions = []
        for _ in range(head_count):
            self.query_dense_layers.append(nn.Linear(input_dim, hidden_dim))
            self.key_dense_layers.append(nn.Linear(input_dim, hidden_dim))
            self.value_dense_layers.append(nn.Linear(input_dim, hidden_dim))
            self.dot_product_attentions.append(
                SingleDotProductAttention(forward_masked=forward_masked))

        self.output_layer = nn.Linear(hidden_dim * self.head_count, input_dim)

    def forward(self, query, key, value, key_mask=None):
        attention_outputs = []

        for query_dense, key_dense, value_dense, attention_layer in zip(
                self.query_dense_layers,
                self.key_dense_layers,
                self.value_dense_layers,
                self.dot_product_attentions,
            ):
            h = attention_layer(
                query_dense(query), key_dense(key), value_dense(value), key_mask)
            attention_outputs.append(h)

        concat = torch.cat(attention_outputs, dim=2)
        outputs = self.output_layer(concat)

        return outputs

class Transformer(nn.Module):
    def __init__(
            self,
            input_dim,
            attention_hidden_dim,
            head_count,
            feed_forward_hidden_dim,
        ):
        super(Transformer, self).__init__()
        self.attention = MultiHeadAttention(
            input_dim, attention_hidden_dim, head_count
        )
        self.layer_norm_after_attention = nn.LayerNorm(input_dim)

        self.hidden_layer = nn.Linear(input_dim, feed_forward_hidden_dim)
        self.output_layer = nn.Linear(feed_forward_hidden_dim, input_dim)
        self.layer_norm_after_feed_forward = nn.LayerNorm(input_dim)

    def forward(self, x, mask=None):
        h = self.attention(x, x, x, mask)
        h = h + x
        h0 = self.layer_norm_after_attention(h)

        h = self.hidden_layer(h0)
        h = self.output_layer(h)
        h = h + h0
        h = self.layer_norm_after_feed_forward(h)

        return h
