"""
REST API variants resource.

.. moduleauthor:: Martijn Vermaat <martijn@vermaat.name>

.. Licensed under the MIT license, see the LICENSE file.
"""


from flask import g, jsonify

from ... import genome
from ...models import Observation, Sample, Variation
from ...region_binning import all_bins
from ...utils import (calculate_frequency, normalize_region, normalize_variant,
                      ReferenceMismatch)
from ..errors import ValidationError
from ..security import has_role
from .base import Resource
from .samples import SamplesResource


class VariantsResource(Resource):
    """
    A variant is represented as an object with the following fields:

    **Note:** This resource is subject to change and therefore not documented
        yet.
    """
    instance_name = 'variant'
    instance_type = 'variant'

    views = ['list', 'get', 'add']

    list_ensure_conditions = [has_role('admin'), has_role('annotator')]
    list_ensure_options = {'satisfy': any}
    list_schema = {'region': {'type': 'dict',
                              'schema': {'chromosome': {'type': 'string', 'required': True, 'maxlength': 30},
                                         'begin': {'type': 'integer', 'required': True},
                                         'end': {'type': 'integer', 'required': True}},
                              'required': True},
                   'sample': {'type': 'sample'}}

    get_ensure_conditions = [has_role('admin'), has_role('annotator')]
    get_ensure_options = {'satisfy': any}
    get_schema = {'sample': {'type': 'sample'}}

    add_ensure_conditions = []
    add_schema = {'chromosome': {'type': 'string', 'required': True, 'maxlength': 30},
                  'position': {'type': 'integer', 'required': True},
                  'reference': {'type': 'string', 'maxlength': 200},
                  'observed': {'type': 'string', 'maxlength': 200}}

    key_type = 'string'

    @classmethod
    def list_view(cls, begin, count, region, sample=None):
        """
        Get a collection of variants.
        """
        if sample:
            if not (sample.public or
                    sample.user is g.user or
                    'admin' in g.user.roles):
                # Todo: Meaningful error message.
                abort(400)

        # Note that in the REST API, we mean begin, end to be one-based and
        # inclusive, but within Varda, everything is zero-based and
        # open-ended.
        try:
            chromosome, begin, end = normalize_region(
                region['chromosome'], region['begin'] - 1, region['end'])
        except ReferenceMismatch as e:
            raise ValidationError(str(e))

        # Exception to the zero-based, open-ended positioning is the
        # region_binning module.
        bins = all_bins(begin + 1, max(begin + 1, end))
        observations = Observation.query.filter(
            Observation.chromosome == chromosome,
            Observation.position >= begin,
            Observation.position <= end,
            Observation.bin.in_(bins))

        # Filter by sample, or by samples with coverage profile otherwise.
        if sample:
            observations = observations \
                .join(Variation).filter_by(sample=sample)
        else:
            observations = observations \
                .join(Variation).join(Sample).filter_by(active=True,
                                                        coverage_profile=True)

        observations = observations.distinct(Observation.chromosome,
                                             Observation.begin,
                                             Observation.end,
                                             Observation.observed)

        items = [cls.serialize((o.chromosome, o.begin, o.end, o.observed),
                               sample=sample)
                 for o in observations.limit(count).offset(begin)]
        return (observations.count(),
                jsonify(collection={'uri': cls.collection_uri(),
                                    'items': items}))


    @classmethod
    def get_view(cls, variant, sample=None):
        """
        Get frequency details for a variant.

        Requires the `admin` or `annotator` role.

        :statuscode 200: Respond with an object defined below as `variant`.

        The response object has the following fields:

        * **uri** (`string`) - URI for this variant.
        * **chromosome** (`string`) - Chromosome name.
        * **position** (`integer`) - Start position of the variant.
        * **reference** (`string`) - Reference sequence.
        * **observed** (`string`) - Observed sequence.
        * **hgvs** (`string`) - HGVS description.
        * **frequency** (`float`) - Frequency in database samples.
        """
        if sample:
            if not (sample.public or
                    sample.user is g.user or
                    'admin' in g.user.roles):
                # Todo: Meaningful error message.
                abort(400)

        return jsonify(variant=cls.serialize(variant, sample=sample))

    @classmethod
    def add_view(cls, chromosome, position, reference='', observed=''):
        """
        Create a variant.
        """
        # Todo: Also support HGVS input.
        try:
            variant = normalize_variant(chromosome, position - 1,
                                        position - 1 + len(reference),
                                        observed, reference=reference)
        except ReferenceMismatch as e:
            raise ValidationError(str(e))
        uri = cls.instance_uri(variant)
        # Note: It doesn't really make sense to calculate global frequencies
        #     here (the client might only be interested in frequencies for
        #     some specific sample), so we only return the URI instead of a
        #     full serialization.
        response = jsonify(variant={'uri': uri})
        response.location = uri
        return response, 201

    @classmethod
    def instance_key(cls, variant):
        return '%s:%d-%d>%s' % variant

    @classmethod
    def serialize(cls, variant, sample=None):
        chromosome, begin, end, observed = variant

        coverage, frequency = calculate_frequency(
            chromosome, begin, end, observed, sample=sample)

        if sample is not None:
            sample_uri = SamplesResource.instance_uri(sample)
        else:
            sample_uri = None

        if genome:
            reference = genome[chromosome][begin:end].upper()
        else:
            reference = 'N' * (end - begin)

        return {'uri': cls.instance_uri(variant),
                'sample_uri': sample_uri,
                'chromosome': chromosome,
                'position': begin + 1,
                'reference': reference,
                'observed': observed,
                'coverage': coverage,
                'frequency': sum(frequency.values()),
                'frequency_het': frequency['heterozygous'],
                'frequency_hom': frequency['homozygous']}
