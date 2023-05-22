import nilearn
import numpy as np
import pandas as pd
import os
import nibabel as nib
import json
from nilearn import datasets
import time
from nilearn.maskers import NiftiLabelsMasker
from nilearn import signal
from sklearn.impute import SimpleImputer
import subprocess as sp


def z_transform_conn_matrix(conn_matrix):
    """
    Applies Fisher's z transform to a connectivity matrix.

    Parameters
    ----------
    conn_matrix : numpy.ndarray
        The connectivity matrix to transform.

    Returns
    -------
    numpy.ndarray
        The transformed connectivity matrix.
    """
    conn_matrix = np.arctanh(conn_matrix) # Fisher's z transform
    if np.isnan(conn_matrix).any(): # remove nans and infs in the matrix
        nan_indices = np.where(np.isnan(conn_matrix))
        conn_matrix[nan_indices] = .0000000001
    if np.isinf(conn_matrix).any():
        inf_indices = np.where(np.isinf(conn_matrix))
        conn_matrix[inf_indices] = 1
    return conn_matrix

class RawDataset():

    def __init__(self, BIDS_path):
        self.BIDS_path = BIDS_path
        if self.BIDS_path is not None:
            pass
        else:
            raise ValueError("The path to the dataset in BIDS format must be specified (BIDS_path).")
        self.data_description_path = self.BIDS_path + '/dataset_description.json'
        self.participant_data_path = self.BIDS_path + '/participants.tsv'
        self._participant_data = pd.read_csv(self.participant_data_path, sep = '\t')
        self._name = None
        self._data_description = None
        self._subjects = None

    def docker_fmriprep(self, subject, fs_license_path, skip_bids_validation = True, fs_reconall = True, mem = 5000, task = 'rest'):
        """
        Runs the fMRIprep pipeline in a Docker container for a given subject.

        Parameters
        ----------
        subject : str
            The label of the participant to process.
        skip_bids_validation : bool, optional
            Whether to skip BIDS validation. Default is True.
        fs_license_path : str, optional
            The path to the (full) FreeSurfer license file
        fs_reconall : bool, optional
            Whether to run FreeSurfer's recon-all. Default is True.
        mem : int, optional
            The amount of memory to allocate to the Docker container, in MB. Default is 5000.
        task : str, optional
            The ID of the task to preprocess, or None to preprocess all tasks. Default is 'rest'.

        Returns
        -------
        None
        """
        data_path = self.BIDS_path
        fmriprep_path = os.path.join(data_path, 'derivatives', 'fmriprep')
        skip_bids_validation = '--skip-bids-validation' if skip_bids_validation else ''
        fs_reconall = '' if fs_reconall else '--fs-no-reconall'
        if task != None:
            task = f'--task-id {task}'
        else:
            task = ''
        fmriprep_bash = f"""
        export PATH="$HOME/.local/bin:$PATH"
        mkdir -p {fmriprep_path}
        export FS_LICENSE={fs_license_path}
        fmriprep-docker {data_path} {fmriprep_path} participant --participant-label {subject} {skip_bids_validation} --fs-license-file $FS_LICENSE {fs_reconall} {task} --stop-on-first-crash --mem_mb {mem} --output-spaces MNI152NLin2009cAsym:res-2 -w $HOME
        """
        if not os.path.exists(f"{self.BIDS_path}/fmriprep_logs"):
            os.makedirs(f"{self.BIDS_path}/fmriprep_logs")
        log_file = f"{self.BIDS_path}/fmriprep_logs/fmriprep_logs_sub-{subject}.txt"
        with open(log_file, "w") as file:
            process = sp.Popen(["bash", "-c", fmriprep_bash], stdout=file, stderr=file, universal_newlines=True)

            while process.poll() is None:
                time.sleep(0.1)

        with open(log_file, "r") as file:
            print(file.read())
    
    @property
    def participant_data(self):
        if self._participant_data is None:
            self._participant_data = pd.read_csv(self.participant_data_path, sep = '\t')
        return self._participant_data

    @property
    def subjects(self):
        if self._subjects is None:
            self._subjects = self._participant_data['participant_id'].values
            self._subjects = np.array([i.replace('sub-', '') for i in self._subjects])
        return self._subjects
    
    @property
    def data_description(self):
        if self._data_description is None:
            self._data_description = json.load(open(self.data_description_path))
        return self._data_description

    @property
    def name(self):
        if self._name is None:
            self._name = self.data_description['Name']
        return self._name
    
    def __repr__(self):
        return f'Dataset(Name={self.name},\nSubjects={self.subjects},\nData_Path={self.BIDS_path})'



class FmriPreppedDataSet(RawDataset):

    def __init__(self, BIDS_path):
        super().__init__(BIDS_path)
        self.data_path = self.BIDS_path + '/derivatives'
        self.data_path = self._find_sub_dirs()
        self.default_confounds_path = os.path.join(os.path.dirname(__file__), "default_confounds.txt")
        self.subject_conn_paths = {}
        for subject in self.subjects:
            output_dir =os.path.join(self.data_path,'clean_data', f'sub-{subject}', 'func')
            if os.path.exists(output_dir):
                conn_mat_paths = [f'{output_dir}/{i}' for i in os.listdir(output_dir) if "conn-matrix" in i]
                if len(conn_mat_paths) != 0:
                    self.subject_conn_paths[subject] = conn_mat_paths[0]
    def __repr__(self):
        return f'Subjects={self.subjects},\n Data_Path={self.data_path})'
    
    def _find_sub_dirs(self):
        """
        Finds the subdirectory containing the subject data.

        Returns
        -------
        str
            The path to the subdirectory containing the subject data.
        """
        path_not_found = True
        while path_not_found:
            try:
                subdirs = os.listdir(self.data_path)
            except FileNotFoundError as e:
                if e.filename == self.data_path and e.strerror == 'No such file or directory':
                    raise FileNotFoundError("The data have not been preprocessed with fmriprep: no 'derivatives' directory found.")
                else:
                    raise e
            for subdir in subdirs:
                if any(subdir.startswith('sub-') for subdir in subdirs):
                        path_not_found = False
                else:
                    if os.path.isdir(os.path.join(self.data_path, subdir)):
                        self.data_path = os.path.join(self.data_path, subdir)
        return self.data_path
    
    def get_ts_paths(self, subject, task): # needs to be adapted to multiple sessions
        #numpy-style docstring
        """
        Parameters
        ----------
        subject : str
            The subject ID.
        task : str
            The task name.
        Returns
        -------
        ts_paths : list
            A list of paths to the time series files.
        """
        
        subject_dir = os.path.join(self.data_path, f'sub-{subject}')
        session_names = self.get_sessions(subject)
        ts_paths = []
        if len(session_names) != 0:
            for session_name in session_names:
                session_dir = os.path.join(subject_dir, f'ses-{session_name}', 'func')
                if os.path.exists(session_dir):
                    ts_paths.extend([f'{session_dir}/{i}' for i in os.listdir(session_dir) if task in i and i.endswith('MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz')])
        else:
            subject_dir = os.path.join(subject_dir, 'func')
            ts_paths = [f'{subject_dir}/{i}' for i in os.listdir(subject_dir) if task in i and i.endswith('MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz')] #sub-01_task-rest_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz
        return ts_paths
    
    def get_sessions(self, subject):
        """
        Returns a list of session names for a given subject. If the subject has no sessions, an empty list is returned.

        Parameters
        ----------
        subject : str
            The label of the subject to retrieve session names for.

        Returns
        -------
        list of str
            A list of session names for the given subject.
        """
        subject_dir = f'{self.data_path}/sub-{subject}'
        subdirs = os.listdir(subject_dir)
        session_names = []
        for subdir in subdirs:
            if subdir.startswith('ses-'):
                session_names.append(subdir[4:])
        return session_names
    
    def _impute_nans_confounds(self, dataframe, pick_confounds = None):
        """
        Parameters
        ----------
        dataframe : pandas.DataFrame
            The dataframe containing the confounds.
        pick_confounds : list or numpy.ndarray
            The confounds to be picked from the dataframe.
        Returns
        -------
        df_no_nans : pandas.DataFrame
            The dataframe with the confounds without NaNs.
        """
        imputer = SimpleImputer(strategy='mean')
        if pick_confounds is None:
            pick_confounds = np.loadtxt(self.default_confounds_path, dtype = 'str')
        if isinstance(pick_confounds, (list, np.ndarray)):
            df_no_nans = pd.DataFrame(imputer.fit_transform(dataframe), columns=dataframe.columns)[pick_confounds]
        else:
            df_no_nans = pd.DataFrame(imputer.fit_transform(dataframe), columns=dataframe.columns)
        return df_no_nans
    
    def get_confounds(self, subject, task, no_nans = True, pick_confounds = None):
        """
        Returns a list of confounds for a given subject and task.

        Parameters
        ----------
        subject : str
            The ID of the subject.
        task : str
            The name of the task.
        no_nans : bool, optional
            Whether to impute NaNs in the confounds. Default is True.
        pick_confounds : list or numpy.ndarray, optional
            The confounds to be picked from the dataframe. If None, the default confounds will be used. Default is None.

        Returns
        -------
        list
            A list of confounds.
        """
        if pick_confounds == None:
            pick_confounds = np.loadtxt(self.default_confounds_path, dtype = 'str')
        else:
            pick_confounds = np.loadtxt(pick_confounds, dtype = 'str')
        subject_dir = os.path.join(self.data_path, f'sub-{subject}')
        session_names = self.get_sessions(subject)

        if len(session_names) != 0:
            confound_paths = []
            confound_list = []
            for session_name in session_names:
                session_dir = os.path.join(subject_dir, f'ses-{session_name}', 'func')
                if os.path.exists(session_dir):
                    confound_files = [os.path.join(session_dir, f) for f in os.listdir(session_dir) if task in f and f.endswith('confounds_timeseries.tsv')]
                    confound_paths.extend(confound_files)
                    
            if no_nans == True:
                for confounds_path in confound_paths:
                    confounds = pd.read_csv(confounds_path, sep = '\t')
                    confounds = self._impute_nans_confounds(confounds)
                    confound_list.append(confounds)
            else:
                for confounds_path in confound_paths:
                    confounds = pd.read_csv(confounds_path, sep = '\t')[pick_confounds]
                    confound_list.append(confounds)
        else:
            func_dir = os.path.join(subject_dir, "func")
            confound_files = [os.path.join(func_dir, f) for f in os.listdir(func_dir) if task in f and f.endswith('confounds_timeseries.tsv')]
            if no_nans == True:
                confound_list = [self._impute_nans_confounds(pd.read_csv(i, sep = '\t'), pick_confounds) for i in confound_files]
            else:
                confound_list = [pd.read_csv(i, sep = '\t') for i in confound_files]

        return confound_list
    
    def parcellate(self, subject, parcellation = 'schaefer',task ="rest", n_parcels = 1000, gsr = False): # adapt to multiple sessions
        """
        Parameters
        ----------
        subject : str
            subject id
        parcellation : str
            parcellation to use
        task : str
            task to use
        n_parcels : int
            number of parcels to use
        gsr : bool  
            whether to use global signal regression
        Returns
        -------
        parc_ts_list : list
            list of parcellated time series
        """
        atlas = None
        if parcellation == 'schaefer':
            atlas = datasets.fetch_atlas_schaefer_2018(n_rois=n_parcels, yeo_networks=7, resolution_mm=1, base_url= None, resume=True, verbose=1)
        masker =  NiftiLabelsMasker(labels_img=atlas.maps, standardize=True, memory='nilearn_cache', verbose=5)

        parc_ts_list = []
        subject_ts_paths = self.get_ts_paths(subject, task)
        confounds = self.get_confounds(subject, task)
        for subject_ts, subject_confounds in zip(subject_ts_paths, confounds):
            if gsr == False:
                parc_ts = masker.fit_transform(subject_ts, confounds = subject_confounds.drop("global_signal", axis = 1))
                parc_ts_list.append(parc_ts)
            else:
                parc_ts = masker.fit_transform(subject_ts, confounds = subject_confounds)
                parc_ts_list.append(parc_ts)
        return parc_ts_list
    
    def clean_signal(self, subject, task="rest", parcellation='schaefer', n_parcels=1000, gsr=False, save = False, save_to = None): # add a save option + path
        """
        Cleans the time series for a given subject using a specified parcellation.

        Parameters
        ----------
        subject : str
            The ID of the subject to clean the time series for.
        task : str, optional
            The name of the task to use. Default is 'rest'.
        parcellation : str, optional
            The name of the parcellation to use. Default is 'schaefer'.
        n_parcels : int, optional
            The number of parcels to use. Default is 1000.
        gsr : bool, optional
            Whether to use global signal regression. Default is False.
        save : bool, optional
            Whether to save the cleaned time series. Default is False.
        save_to : str, optional
            The path to save the cleaned time series. If None, the time series will be saved to the default directory. Default is None.

        Returns
        -------
        np.ndarray
            The cleaned time series of shape (n_sessions, n_parcels, n_volumes).
        """
        parc_ts_list = self.parcellate(subject, parcellation, task, n_parcels, gsr)
        clean_ts_array =[]
        for parc_ts in parc_ts_list:
            clean_ts = signal.clean(parc_ts, t_r = 2, low_pass=0.08, high_pass=0.01, standardize=True, detrend=True)
            clean_ts_array.append(clean_ts[10:]) # discarding first 10 volumes
        clean_ts_array = np.array(clean_ts_array)
        print(clean_ts_array.shape)
        if save == True:
            if save_to is None:
                save_dir = os.path.join(f'{self.data_path}', 'clean_data', f'sub-{subject}', 'func')
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                save_to = os.path.join(f'{save_dir}', f'clean-ts-sub-{subject}-{task}-{parcellation}{n_parcels}.npy')
            else:
                save_to = os.path.join(save_to, f'clean-ts-sub-{subject}-{task}-{parcellation}{n_parcels}.npy')
            print(save_to)
            np.save(save_to, clean_ts_array)
        return clean_ts_array
    
    def get_conn_matrix(self, subject, subject_ts = None, parcellation = 'schaefer', task = 'rest', concat_ts = False, n_parcels = 1000, gsr = False, z_transformed = True, save = False, save_to = None):
        """
        Computes the connectivity matrix for a given subject.

        Parameters
        ----------
        subject : str
            The ID of the subject to compute the connectivity matrix for.
        subject_ts : str, optional
            The path to the cleaned time series. If None, the time series will be cleaned using the `clean_signal` method. Default is None.
        parcellation : str, optional
            The name of the parcellation to use. Default is 'schaefer'.
        task : str, optional
            The name of the task to use. Default is 'rest'.
        concat_ts : bool, optional
            Whether to compute the connectivity matrix on concatenated time series (e.g., if several sessions available). Default is False.
        n_parcels : int, optional
            The number of parcels to use. Default is 1000.
        gsr : bool, optional
            Whether to use global signal regression. Default is False.
        z_transformed : bool, optional
            Whether to apply Fisher's z transform to the connectivity matrix. Default is True.
        save : bool, optional
            Whether to save the connectivity matrix. Default is False.
        save_to : str, optional
            The path to save the connectivity matrix. If None, the matrix will be saved to the default directory. Default is None.

        Returns
        -------
        np.ndarray
            The connectivity matrix of shape (n_sessions, n_parcels, n_parcels).
        """
        if subject_ts is None:
            subj_ts_array = self.clean_signal(subject, task, parcellation, n_parcels, gsr)
        else:
            subj_ts_array = np.load(subject_ts)
        if concat_ts == True:
            subj_ts_array = np.row_stack(subj_ts_array)
            conn_matrix = np.corrcoef(subj_ts_array.T)
            if z_transformed == True:
                conn_matrix = z_transform_conn_matrix(conn_matrix)
        else:
            conn_matrix = np.zeros((subj_ts_array.shape[0], n_parcels, n_parcels))
            for i, subj_ts in enumerate(subj_ts_array):
                conn_matrix[i] = np.corrcoef(subj_ts.T)
                if z_transformed == True:
                    conn_matrix[i] = z_transform_conn_matrix(conn_matrix[i])
        if save == True:
            if save_to is None:
                save_dir = os.path.join(f'{self.data_path}', 'clean_data', f'sub-{subject}', 'func')
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                save_to = os.path.join(save_dir, f'conn-matrix-sub-{subject}-{task}-{parcellation}{n_parcels}.npy')
            else:
                save_to = os.path.join(save_to, f'conn-matrix-sub-{subject}-{task}-{parcellation}{n_parcels}.npy')

            self.subject_conn_paths[subject] = save_to

            np.save(save_to, conn_matrix)
        return conn_matrix