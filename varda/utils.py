"""
Various utilities for Varda.

.. note:: All genomic positions in this module are one-based and inclusive.

.. moduleauthor:: Martijn Vermaat <martijn@vermaat.name>

.. Licensed under the MIT license, see the LICENSE file.
"""


from __future__ import division

import collections
import hashlib
import itertools

import binning
from flask import current_app
from sqlalchemy.sql import func

from . import db, genome
from .models import Coverage, DataSource, Observation, Region, Sample, Variation


class ReferenceMismatch(Exception):
    """
    Exception thrown mismatch with reference.
    """
    pass


class NoGenotypesInRecord(Exception):
    """
    Exception thrown when reading a genotype while there are no genotypes in
    the record (or anything we could derive them from anyway).
    """
    pass


def digest(data):
    """
    Given a file-like object opened for reading, calculate a digest as SHA1
    checksum and number of records.

    Calculating the number of records is done in a naive way by counting the
    number of lines in the file, and as such includes empty and header lines.
    """
    def read_chunks(data, chunksize=0xf00000):
        # Default chunksize is 16 megabytes.
        while True:
            chunk = data.read(chunksize)
            if not chunk:
                break
            yield chunk

    sha1 = hashlib.sha1()
    records = 0
    for chunk in read_chunks(data):
        sha1.update(chunk)
        records += chunk.count('\n')
    return sha1.hexdigest(), records


def chromosome_compare_key(chromosome):
    """
    Key to compare chromosomes by in sorting. Can be used as `key` argument in
    the :func:`sorted`, :func:`max` and :func:`min` functions.

    :arg chromosome: Chromosome name.
    :type chromosome: str

    :return: Compare key for `chromosome`.
    :rtype: comparable
    """
    if chromosome.startswith('chr'):
        chromosome = chromosome[3:]
    parts = chromosome.split('_')
    return len(parts), [int(p) if p.isdigit() else p for p in parts]


def normalize_chromosome(chromosome):
    """
    Try to get normalized chromosome name by reference lookup.
    """
    if chromosome.startswith('chr'):
        chromosome = chromosome[3:]

    if not genome:
        for aliases in current_app.config['CHROMOSOME_ALIASES']:
            if chromosome in aliases or 'chr' + chromosome in aliases:
                return aliases[0]
        return chromosome

    if chromosome in genome:
        return chromosome
    elif 'chr' + chromosome in genome:
        return 'chr' + chromosome

    for aliases in current_app.config['CHROMOSOME_ALIASES']:
        if chromosome in aliases or 'chr' + chromosome in aliases:
            for alias in aliases:
                if alias in genome:
                    return alias

    raise ReferenceMismatch('Chromosome "%s" not in reference genome' %
                            chromosome)


def normalize_region(chromosome, begin, end):
    """
    Use reference to normalize chromosome name and validate location.

    :arg chromosome: Chromosome name.
    :type chromosome: str
    :arg begin: Beginning of genomic region, one-based.
    :type begin: int
    :arg end: End of genomic region, one-based, inclusive.
    :type end: int

    :return: Normalized region as a tuple of `chromosome`, `begin`, `end`.
    :rtype: (str, int, int)
    """
    chromosome = normalize_chromosome(chromosome)

    # Todo: Probably raise an exception if begin > end.

    if genome:
        if end > len(genome[chromosome]):
            raise ReferenceMismatch('Position %d does not exist on chromosome'
                                    ' "%s" in reference genome' %
                                    (end, chromosome))

    return chromosome, begin, end


def normalize_variant(chromosome, position, reference, observed):
    """
    Use reference to create a normalized representation of the variant.

    :arg chromosome: Chromosome name.
    :type chromosome: str
    :arg position: One-based position where `reference` and `observed` start
        on the reference genome
    :type position: int
    :arg reference: Reference sequence.
    :type reference: str
    :arg observed: Observed sequence.
    :type observed: str

    :return: Normalized variant representation as a tuple of `chromosome`,
        `position`, `reference`, `observed`.
    :rtype: (str, int, str, str)
    """
    reference = reference.upper()
    observed = observed.upper()

    chromosome = normalize_chromosome(chromosome)

    if genome:
        if position > len(genome[chromosome]):
            raise ReferenceMismatch('Position %d does not exist on chromosome'
                                    ' "%s" in reference genome' %
                                    (position, chromosome))
        if (genome[chromosome][position - 1
                               :position + len(reference) - 1].upper() !=
            reference):
            raise ReferenceMismatch('Sequence "%s" does not match reference'
                                    ' genome on "%s" at position %d' %
                                    (reference, chromosome, position))

    prefix, reference, observed, _ = trim_common(reference, observed)
    position += prefix

    # Todo: If reference == observed == '', there is no variant. Probably
    #     raise an exception in that case.

    if not genome:
        return chromosome, position, reference, observed

    # Insertions and deletions can be moved to the left by looking for cyclic
    # permutations.
    if reference == '':
        position, observed = move_left(genome[chromosome], position, observed)
        observed = observed.upper()
    elif observed == '':
        position, reference = move_left(genome[chromosome], position, reference)
        reference = reference.upper()

    return chromosome, position, reference, observed


def trim_common(s1, s2):
    """
    Trim two sequences by removing the longest common prefix and suffix. Also
    report the lengths of the removed parts. We start by removing the suffix.

    Standard convention with VCF is to place an indel at the left-most
    position, but some tools add additional context to the right of the
    sequences (e.g. samtools). These common suffixes are undesirable when
    comparing variants, for example in variant databases.

    Also, VCF requires to report at least one reference base, even for
    insertions.

        >>> trim_common('TATATATA', 'TATATA')
        (0, 'TA', '', 6)

        >>> trim_common('ACCCCC', 'ACCCCCCCC')
        (1, '', 'CCC', 5)

    :arg s1: First sequence.
    :type s1: str
    :arg s2: Second sequence.
    :type s2: str

    :return: Tuple (cpl, trimmed s1, trimmed s2, csl) where cpl and csl are
        the lengths of the common prefix and suffix, respectively.
    """
    suffix = 0
    while suffix < min(len(s1), len(s2)) and s1[-1 - suffix] == s2[-1 - suffix]:
        suffix += 1

    if suffix:
        s1 = s1[:-suffix]
        s2 = s2[:-suffix]

    prefix = 0
    while prefix < min(len(s1), len(s2)) and s1[prefix] == s2[prefix]:
        prefix += 1

    return prefix, s1[prefix:], s2[prefix:], suffix


def move_left(context, position, sequence):
    """
    Move `sequence` as far as possible to the left, starting at `position`
    (one-based) in `context`, while staying in cyclic permutations.

    Schematic example::

                                       [=== sequence ====]
          [======================= context =======================]
                             <-- [== permutation ==]

                                       ^
                                    position

    Code examples::

        >>> move_left('abbaabbaabba', 5, 'abba')
        (1, 'abba')
        >>> move_left('abbaabbaabba', 6, 'bbaa')
        (1, 'abba')
        >>> move_left('abbaabbaabba', 6, 'bba')
        (5, 'abb')

    :arg context: Context sequence.
    :type context: str (or really a subscriptable yielding strings)
    :arg position: Start position of `sequence` in `context`, one-based.
    :type position: int
    :arg sequence: Sequence to find cyclic permutations of in `context`.
    :type sequence: str

    :return: A tuple (permutation, position) being the resulting cyclic
        permutation of `sequence` and its position in `context`.
    :rtype: (str, int)
    """
    def lookup(p):
        if position <= p < position + len(sequence):
            return sequence[p - position].upper()
        return context[p - 1].upper()

    move = 0
    while (position - move > 1 and
           lookup(position - move - 1) ==
           lookup(position + len(sequence) - move - 1)):
        move += 1

    if not move:
        # Note: This case is only needed because the general case fails for
        #     move == 0 since sequence[:-0] == ''.
        return position, sequence

    return (position - move,
            context[position - move - 1
                    :min(position, position - move + len(sequence)) - 1]
            + sequence[:-move])


def read_genotype(call, prefer_likelihoods=False):
    """
    Read genotype from a call, either using GT or deducing it from GL or PL.

    :arg call: Genotype call for a sample.
    :type call: vcf.model._Call
    :arg prefer_likelihoods: Whether or not to prefer deriving genotypes from
        likelihoods (if available).
    :type prefer_likelihoods: bool

    :return: (Most-likely) genotype for the call, or `None` if unknown. The
        genotype is encoded as a list of integers (length is sample ploidy),
        refering to the reference (`0`) or variant (`1`, `2`, ...) alleles.
    :raise NoGenotypesInRecord: If the record for the given call has no
        genotype information.
    """
    fields = call.site.FORMAT.split(':')

    if not any(x in fields for x in ('GT', 'GL', 'PL')):
        raise NoGenotypesInRecord('The record for the given call has no '
                                  'genotypes defined and nothing to derive '
                                  'them from')

    if prefer_likelihoods or 'GT' not in fields:
        if 'GL' in fields or 'PL' in fields:
            # Get ploidy from GT, default to diploid.
            try:
                ploidy = len(call.gt_alleles)
            except AttributeError:
                ploidy = 2

            # All possible genotypes given alleles and call ploidy. Example
            # (diploid, two alt alleles):
            #
            #     genotypes = [(0, 0), (0, 1), (1, 1), (0, 2), (1, 2), (2, 2)]
            genotypes = sorted(itertools.combinations_with_replacement(
                                 range(len(call.site.ALT) + 1), ploidy),
                               key=lambda g: g[::-1])

            if 'PL' in fields:
                return genotypes[min((call.data.PL[i], i)
                                     for i in range(len(genotypes)))[1]]
            elif 'GL' in fields:
                return genotypes[min((-call.data.GL[i], i)
                                     for i in range(len(genotypes)))[1]]

    # If we didn't deduce it yet, and it was called, use GT.
    if call.called:
        return [int(a) for a in call.gt_alleles]


def calculate_frequency(chromosome, position, reference, observed,
                        samples=None):
    """
    Calculate frequency for a variant within a set of samples.

    :arg chromosome: Chromosome name.
    :type chromosome: str
    :arg position: One-based position where `reference` and `observed` start
        on the reference genome
    :type position: int
    :arg reference: Reference sequence.
    :type reference: str
    :arg observed: Observed sequence.
    :type observed: str
    :arg samples: Calculate the frequency within these samples.
    :type samples: list of Sample

    :return: A tuple of the number of individuals having coverage and a
        dictionary with for every zygosity the ratio of individuals with
        observed allele and zygosity.
    :rtype: (int, dict)
    """
    samples = samples or []

    # Todo: Use constant definition for zygosity, probably shared with the
    #     one used in the models.
    zygosities = (None, 'homozygous', 'heterozygous')

    end_position = position + max(1, len(reference)) - 1
    bins = binning.containing_bins(position - 1, end_position)

    # Coverage over samples with coverage profile.
    coverage = Region.query.join(Coverage).filter(
        Region.bin.in_(bins),
        Region.chromosome == chromosome,
        Region.begin <= position,
        Region.end >= end_position,
        Coverage.sample_id.in_(sample.id for sample in samples
                               if sample.coverage_profile)
    ).count()

    # Add the number of individuals in samples without coverage profile.
    coverage += sum(sample.pool_size for sample in samples
                    if not sample.coverage_profile)

    if not coverage:
        return 0, {zygosity: 0 for zygosity in zygosities}

    # Counts of observations per zygosity.
    counts = db.session.query(
        Observation.zygosity,
        func.sum(Observation.support)
    ).join(Variation).filter(
        Observation.bin.in_(bins),
        Observation.chromosome == chromosome,
        Observation.position == position,
        Observation.reference == reference,
        Observation.observed == observed,
        Variation.sample_id.in_(sample.id for sample in samples)
    ).group_by(Observation.zygosity)

    counts = collections.Counter(dict(counts))

    frequency = {zygosity: counts[zygosity] / coverage
                 for zygosity in zygosities}

    return coverage, frequency
