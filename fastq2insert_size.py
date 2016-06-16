#!/usr/bin/env python
desc="""Estimate insert size by aligning subset of reads onto contigs. 

PREREQUISITIES:
- BWA
"""
epilog="""Author:
l.p.pryszcz@gmail.com

Mizerow, 10/04/2015
"""

import math, os, sys, commands, subprocess
from datetime import datetime

def flag2orientation(flag):
    """Return pair orientation: FF: 0; FR: 1; RF: 2; RR: 4."""
    ##FR/RF
    #if alg.is_reverse != alg.mate_is_reverse:
    if flag&16 != flag&32:
        #FR
        #if alg.is_read1 and not alg.is_reverse or \
        #   alg.is_read2 and not alg.is_reverse:
        if flag&64 and not flag&16 or flag&128 and not flag&16:
            return 1
        #RF
        else:
            return 2
    #RR - double check that!
    #elif alg.is_read1 and alg.is_reverse or \
    #     alg.is_read2 and not alg.is_reverse:
    if flag&64 and flag&16 or flag&128 and not flag&16:
        return 3
    #FF
    else:
        return 0
def get_bwa_subprocess(fq1, fq2, fasta, threads, verbose):
    """Return bwa subprocess"""
    # generate index if missing
    if not os.path.isfile(fasta+".bwt"):
        cmd = "bwa index %s"%fasta
        #if verbose:
        #    sys.stderr.write(" %s\n"%cmd)
        bwtmessage = commands.getoutput(cmd)
    # start BWA alignment stream
    cmd = ["bwa", "mem", "-S", "-t %s"%threads, fasta, fq1, fq2]
    #if verbose:
    #    sys.stderr.write(" %s\n"%" ".join(cmd))
    bwa = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return bwa

def percentile(N, percent):
    """
    Find the percentile of a list of values. 

    @parameter N - is a list of values. Note N MUST BE already sorted.
    @parameter percent - a float value from 0.0 to 1.0.

    @return - the percentile of the values

    From http://code.activestate.com/recipes/511478-finding-the-percentile-of-the-values/
    """
    if not N:
        return None
    k = (len(N)-1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return key(N[int(k)])
    d0 = key(N[int(f)]) * (c-k)
    d1 = key(N[int(c)]) * (k-f)
    return d0+d1

def median(N):
    """median is 50th percentile."""
    return percentile(N, 0.5)

def mean(data):
    """Return the sample arithmetic mean of data.
    http://stackoverflow.com/a/27758326/632242
    """
    n = len(data)
    if n < 1:
        raise ValueError('mean requires at least one data point')
    return sum(data)/float(n) 

def stdev(data):
    """Return sum of square deviations of sequence data."""
    c = mean(data)
    ss = sum((x-c)**2 for x in data)
    return ss
    
def get_isize_stats(fq1, fq2, fasta, mapqTh=10, threads=1,
                    limit=1e5, verbose=0, percentile=5): 
    """Return estimated insert size median, mean, stdev and
    pairing orientation counts (FF, FR, RF, RR). 
    Ignore bottom and up percentile for insert size statistics. 
    """
    # read dumped info
    if os.path.isfile(fq2+".is.txt"):
        ldata = open(fq2+".is.txt").readline().split("\t")
        if len(ldata) == 7:
            ismedian, ismean, isstd = map(float, ldata[:3])
            pairs = map(int, ldata[3:])
            # skip insert size estimation only if satisfactory previous estimate 
            if sum(pairs)*2 >= limit and isstd / ismean < 0.66:
                return ismedian, ismean, isstd, pairs
    #if verbose:
    #    sys.stderr.write("Starting alignment...\n")
    bwa = get_bwa_subprocess(fq1, fq2, fasta, threads, verbose)
    # parse alignments
    #if verbose:
    #    sys.stderr.write("Estimating insert size stats...\n")
    isizes = []
    pairs = [0, 0, 0, 0]
    #read from stdin
    for i, sam in enumerate(bwa.stdout, 1):
        if sam.startswith("@"):
            continue
        if not i%1000:
            sys.stderr.write(' %s %s \r'%(i, len(isizes)))
        # read sam entry
        rname, flag, chrom, pos, mapq, cigar, mchrom, mpos, isize, seq = sam.split('\t')[:10]
        flag, pos, mapq, mpos, isize = map(int, (flag, pos, mapq, mpos, isize))
        # take only reads with good alg quality and one read per pair
        # ignore not primary and supplementary alignments
        if mapq < mapqTh or isize < 1 or flag&256 or flag&2048: # or not flag&2:
            continue
        #store isize
        isizes.append(isize)
        #store pair orientation
        pairs[flag2orientation(flag)] += 1
        #stop if limit reached
        if len(isizes) >= limit:
            break
    if sum(pairs)<100:
        return 0, 0, 0, []
    #get rid of 5 percentile from both sides
    isizes.sort()
    maxins = percentile(isizes, 0.01*(100-percentile)) 
    minins = percentile(isizes, 0.01*percentile) 
    isizes = [x for x in isizes if x>minins and x<maxins]
    # get stats
    ismedian, ismean, isstd = median(isizes), mean(isizes), stdev(isizes)
    # save info
    try:
        with open(fq2+".is.txt", "w") as out:
            out.write("%s\t%s\t%s\t%s\n"%(ismedian, ismean, isstd, "\t".join(map(str, pairs))))
    except:
        sys.stderr.write("[WARNING] Couldn't write library statistics to %s\n"%(fq2+".is.txt",))
    return ismedian, ismean, isstd, pairs

def fastq2insert_size(out, fastq, fasta, mapq, threads, limit, verbose, log=sys.stderr):
    """Report insert size statistics and return all information."""
    header  = "Insert size statistics\t\t\t\tMates orientation stats\n"
    header += "FastQ files\tmedian\tmean\tstdev\tFF\tFR\tRF\tRR\n"
    if verbose:
        out.write(header)
    line = "%s %s\t%i\t%.2f\t%.2f\t%s\n"
    data = []
    for fq1, fq2 in zip(fastq[0::2], fastq[1::2]):
        # get IS stats
        ismedian, ismean, isstd, pairs = get_isize_stats(fq1, fq2, fasta, mapq, threads, limit, verbose)
        if not sum(pairs):
            log.write("[WARNING] No alignments for %s - %s!\n"%(fq1, fq2))
            continue
        # report
        if verbose:
            out.write(line%(fq1, fq2, ismedian, ismean, isstd, "\t".join(map(str, pairs))))
        # store data
        data.append((fq1, fq2, ismedian, ismean, isstd, pairs))
    return data
    
def main():
    import argparse
    usage   = "%(prog)s -v" #usage=usage, 
    parser  = argparse.ArgumentParser(description=desc, epilog=epilog, \
                                      formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-v", dest="verbose",  default=False, action="store_true", help="verbose")    
    parser.add_argument('--version', action='version', version='1.0a')   
    parser.add_argument("-i", "--fastq", nargs="+", 
                        help="FASTQ PE/MP files")
    parser.add_argument("-f", "--fasta", #type=file, 
                        help="reference assembly FASTA file")
    parser.add_argument("-o", "--output",  default=sys.stdout, type=argparse.FileType("w"), 
                        help="output stream [stdout]")
    parser.add_argument("-l", "--limit",  default=10000, type=int, 
                        help="align l reads [%(default)s]")
    parser.add_argument("-q", "--mapq",    default=10, type=int, 
                        help="min mapping quality for variants [%(default)s]")
    parser.add_argument("-t", "--threads", default=1, type=int, 
                        help="max threads to run [%(default)s]")

    o = parser.parse_args()
    if o.verbose:
        sys.stderr.write("Options: %s\n"%str(o))
        
    fastq2insert_size(o.output, o.fastq, o.fasta, o.mapq, o.threads, \
                      o.limit, o.verbose)

if __name__=='__main__': 
    t0 = datetime.now()
    try:
        main()
    except KeyboardInterrupt:
        sys.stderr.write("\nCtrl-C pressed!      \n")
    except IOError as e:
        sys.stderr.write("I/O error({0}): {1}\n".format(e.errno, e.strerror))
    dt = datetime.now()-t0
    sys.stderr.write("#Time elapsed: %s\n"%dt)
