#!/usr/bin/env python
""" Kallisto pipeline """

import sys
from argparse import ArgumentParser
import yaml
import pypiper
import os

try:
	from pipelines.models import AttributeDict
	from pipelines import toolkit as tk
except:
	sys.path.append(os.path.join(os.path.dirname(__file__), "pipelines"))
	from looper.models import AttributeDict
	from pypiper import ngstk as tk


__author__ = "Andre Rendeiro"
__copyright__ = "Copyright 2015, Andre Rendeiro"
__credits__ = []
__license__ = "GPL2"
__version__ = "0.2"
__maintainer__ = "Andre Rendeiro"
__email__ = "arendeiro@cemm.oeaw.ac.at"
__status__ = "Development"



def main():
	# Parse command-line arguments
	parser = ArgumentParser(prog="rnaKallisto", description="Kallisto pipeline")
	parser = arg_parser(parser)
	parser = pypiper.add_pypiper_args(parser, all_args = True)
	args = parser.parse_args()

	# Read in yaml configs
	sample = AttributeDict(yaml.load(open(args.sample_config, "r")))
	path_conf_file = os.path.join(os.path.dirname(__file__), args.config_file)
	pipeline_config = AttributeDict(yaml.load(open(path_conf_file), "r"))

	# Start main function
	process(sample, pipeline_config, args)



def arg_parser(parser):
	"""
	Global options for pipeline.
	"""
	parser.add_argument(
		"-y", "--sample-yaml",
		dest="sample_config",
		help="Yaml config file with sample attributes.",
		type=str
	)
	parser.add_argument(
		"-qs","--quantseq",
		dest="quantseq",
		action="store_true",
		default=False,
		help="Enables quantseq specific options"
	)
	return parser


def process(sample, pipeline_config, args):
	"""
	This takes unmapped Bam files and makes trimmed, aligned, duplicate marked
	and removed, indexed, shifted Bam files along with a UCSC browser track.
	Peaks are called and filtered.
	"""

	print("Start processing sample %s." % sample.sample_name)

	# for path in ["sample_root"] + sample.paths.__dict__.keys():
	# 	if not os.path.exists(sample.paths[path]):
	# 		try:
	# 			os.mkdir(sample.paths[path])
	# 		except OSError("Cannot create '%s' path: %s" % (path, sample.paths[path])):
	# 			raise

	# Start Pypiper object
	pm = pypiper.PipelineManager("rnaKallisto", sample.paths.sample_root, args=args)

	print "\nPipeline configuration:"
	print(pm.config)
	tools = pm.config.tools  # Convenience alias
	param = pm.config.parameters
	resources = pm.config.resources

	raw_folder = os.path.join(sample.paths.sample_root, "raw")
	fastq_folder = os.path.join(sample.paths.sample_root, "fastq")

	sample.paired = False
	if args.single_or_paired == "paired":
		sample.paired = True

	# Create a ngstk object
	ngstk = pypiper.NGSTk(pm=pm)

	# Convert bam to fastq
	pm.timestamp("Converting to Fastq format")

	local_input_files = ngstk.merge_or_link([args.input, args.input2], raw_folder, args.sample_name)
	cmd, out_fastq_pre, unaligned_fastq = ngstk.input_to_fastq(local_input_files, args.sample_name, sample.paired, fastq_folder)
	pm.run(cmd, unaligned_fastq, 
		follow=ngstk.check_fastq(local_input_files, unaligned_fastq, sample.paired))
	pm.clean_add(out_fastq_pre + "*.fastq", conditional=True)

	pm.report_result("File_mb", ngstk.get_file_size(local_input_files))
	pm.report_result("Read_type", args.single_or_paired)
	pm.report_result("Genome", args.genome_assembly)

	sample.fastq = out_fastq_pre + "_R1.fastq"
	sample.trimmed = out_fastq_pre + "_R1_trimmed.fastq"
	sample.fastq1 = out_fastq_pre + "_R1.fastq" if sample.paired else None
	sample.fastq2 = out_fastq_pre + "_R2.fastq" if sample.paired else None
	sample.trimmed1 = out_fastq_pre + "_R1_trimmed.fastq" if sample.paired else None
	sample.trimmed1Unpaired = out_fastq_pre + "_R1_unpaired.fastq" if sample.paired else None
	sample.trimmed2 = out_fastq_pre + "_R2_trimmed.fastq" if sample.paired else None
	sample.trimmed2Unpaired = out_fastq_pre + "_R2_unpaired.fastq" if sample.paired else None

	#if not sample.paired:
	#	pm.clean_add(sample.fastq, conditional=True)
	#if sample.paired:
	#	pm.clean_add(sample.fastq1, conditional=True)
	#	pm.clean_add(sample.fastq2, conditional=True)
	#	pm.clean_add(sample.fastqUnpaired, conditional=True)

	# Trim reads
	pm.timestamp("Trimming adapters from sample")
	if pipeline_config.parameters.trimmer == "trimmomatic":

		inputFastq1 = sample.fastq1 if sample.paired else sample.fastq
		inputFastq2 = sample.fastq2 if sample.paired else None
		outputFastq1 = sample.trimmed1 if sample.paired else sample.trimmed
		outputFastq1unpaired = sample.trimmed1Unpaired if sample.paired else None
		outputFastq2 = sample.trimmed2 if sample.paired else None
		outputFastq2unpaired = sample.trimmed2Unpaired if sample.paired else None

		PE = sample.paired
		pe = "PE" if PE else "SE"
		cmd = tools.java + " -Xmx" + str(pm.mem) + " -jar " + tools.trimmomatic
		cmd += " {0} -threads {1} {2}".format(pe, args.cores, inputFastq1)
		if PE:
			cmd += " {0}".format(inputFastq2)
		cmd += " {0}".format(outputFastq1)
		if PE:
			cmd += " {0} {1} {2}".format(outputFastq1unpaired, outputFastq2, outputFastq2unpaired)
		if args.quantseq: cmd += " HEADCROP:6"
		cmd += " ILLUMINACLIP:" + resources.adapters + ":2:10:4:1:true"
		if args.quantseq: cmd += " ILLUMINACLIP:" + "/data/groups/lab_bsf/resources/trimmomatic_adapters/PolyA-SE.fa" + ":2:30:5:1:true"
		cmd += " SLIDINGWINDOW:4:1"
		cmd += " MAXINFO:16:0.40"
		cmd += " MINLEN:21"


		pm.run(cmd, sample.trimmed1 if sample.paired else sample.trimmed, shell=True, nofail=True,
			follow = ngstk.check_trim(sample.trimmed, sample.paired, sample.trimmed2,
				fastqc_folder = os.path.join(sample.paths.sample_root, "fastqc/")))
		if not sample.paired:
			pm.clean_add(sample.trimmed, conditional=True)
		else:
			pm.clean_add(sample.trimmed1, conditional=True)
			pm.clean_add(sample.trimmed1Unpaired, conditional=True)
			pm.clean_add(sample.trimmed2, conditional=True)
			pm.clean_add(sample.trimmed2Unpaired, conditional=True)

	elif pipeline_config.parameters.trimmer == "skewer":
		skewer_dirpath = os.path.join(sample.paths.sample_root, "skewer")
		ngstk.make_dir(skewer_dirpath)
		sample.trimlog = os.path.join(skewer_dirpath, "trim.log")
		cmd = ngstk.skewer(
			inputFastq1=sample.fastq1 if sample.paired else sample.fastq,
			inputFastq2=sample.fastq2 if sample.paired else None,
			outputPrefix=os.path.join(sample.paths.sample_root, "fastq/", sample.sample_name),
			outputFastq1=sample.trimmed1 if sample.paired else sample.trimmed,
			outputFastq2=sample.trimmed2 if sample.paired else None,
			log=sample.trimlog,
			cpus=args.cores,
			adapters=pipeline_config.resources.adapters
		)
		pm.run(cmd, sample.trimmed1 if sample.paired else sample.trimmed, shell=True, nofail=True, 
			follow = ngstk.check_trim(sample.trimmed, sample.paired, sample.trimmed2,
				fastqc_folder = os.path.join(sample.paths.sample_root, "fastqc/")))
		if not sample.paired:
			pm.clean_add(sample.trimmed, conditional=True)
		else:
			pm.clean_add(sample.trimmed1, conditional=True)
			pm.clean_add(sample.trimmed2, conditional=True)

	# With kallisto from unmapped reads
	pm.timestamp("Quantifying read counts with kallisto")

	inputFastq = sample.trimmed1 if sample.paired else sample.trimmed
	inputFastq2 = sample.trimmed1 if sample.paired else None
	transcriptomeIndex = os.path.join(	pm.config.resources.genomes, 
										sample.transcriptome,
										"indexed_kallisto",
										sample.transcriptome + "_kallisto_index.idx")

	bval = 0 # Number of bootstrap samples (default: 0)
	size = 50 # Estimated average fragment length
	sdev = 20 # Estimated standard deviation of fragment length
	sample.paths.quant = os.path.join(sample.paths.sample_root, "kallisto")
	sample.kallistoQuant = os.path.join(sample.paths.quant,"abundance.h5")
	cmd1 = tools.kallisto + " quant -b {0} -l {1} -s {2} -i {3} -o {4} -t {5}".format(bval, size, sdev, transcriptomeIndex, sample.paths.quant, args.cores)
	if not sample.paired:
		cmd1 += " --single {0}".format(inputFastq)
	else:
		cmd1 += " {0} {1}".format(inputFastq, inputFastq2)
	cmd2 = tools.kallisto + " h5dump -o {0} {0}/abundance.h5".format(sample.paths.quant)

	pm.run([cmd1,cmd2], sample.kallistoQuant, shell=True, nofail=True)

	pm.stop_pipeline()
	print("Finished processing sample %s." % sample.sample_name)


if __name__ == '__main__':
	try:
		sys.exit(main())
	except KeyboardInterrupt:
		print("Program canceled by user!")
		sys.exit(1)
