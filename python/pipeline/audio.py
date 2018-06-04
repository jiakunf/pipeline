from itertools import count

from scipy.misc import imresize
import datajoint as dj
from datajoint.jobs import key_hash
from tqdm import tqdm

from pipeline import experiment, notify
from pipeline.exceptions import PipelineException

from warnings import warn
import cv2
import numpy as np
import json
import os
from commons import lab
from datajoint.autopopulate import AutoPopulate


from pipeline.utils.eye_tracking import ROIGrabber, PupilTracker, CVROIGrabber, ManualTracker
from pipeline.utils import ts2sec, read_video_hdf5
from pipeline import config

schema = dj.schema('pipeline_audio', locals())

@schema
class AudioSignal(dj.Imported):
    definition = """"
    # audio timestamps
    sample_length  : int  # total number of samples in audio recording
    audio_time     : longblob

    """