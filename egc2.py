# egc2.py
# Author: Alejandro Sanchez
# Created: Jul 3, 2018
#
# Second version of classifier

import numpy as np
import h5py
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, ConcatDataset, DataLoader
from sklearn.metrics import roc_auc_score
import matplotlib.pyplot as plt

electron_input_file = "SingleElectronFlatPt10To160_2016_25ns_Moriond17MC_PoissonOOTPU_IMG_RH1_n225k.hdf5"
photon_input_file = "SinglePhotonFlatPt10To160_2016_25ns_Moriond17MC_PoissonOOTPU_IMG_RH1_n225k.hdf5"
validation_fraction = 0.15
num_epochs = 12
use_gpu = True

### Prepare Data ###
print("Fetching data...")

class myData(Dataset):
    '''
    custom dataset class that splits input file into training and validation 
    sets.
    '''

    def __init__(self, data_file, val_cut):
        f = h5py.File(data_file, 'r')
        self.inputs = torch.tensor(f['X_crop0'][:]).view(-1, 1, 32, 32)
        answers = torch.tensor(f['y'][:], dtype=torch.int).view(-1)
        self.targets = torch.zeros(len(answers), 2)
        for i, entry in enumerate(self.targets):
            entry[answers[i]] = 1.0
        self.pt_ = torch.tensor(f['pho_pT0'][:]).view(-1)

        self.trainset = [self.inputs[self.valCut(val_cut):], 
                         self.targets[self.valCut(val_cut):],
                         self.pt_[self.valCut(val_cut):]]
        self.valset = [self.inputs[:self.valCut(val_cut)], 
                       self.targets[:self.valCut(val_cut)],
                       self.pt_[:self.valCut(val_cut)]]
        self.use_train_set = True

    def __len__(self):
        if self.use_train_set:
            return len(self.trainset[0])
        else:
            return len(self.valset[0])

    def __getitem__(self, index):
        if self.use_train_set:
            return self.trainset[0][index], self.trainset[1][index],\
                    self.trainset[2][index]
        else:
            return self.valset[0][index], self.valset[1][index],\
                    self.valset[2][index]

    def valCut(self, fraction):
        return int(len(self.inputs) * fraction)

    def useTrainSet(self, use_train_set_):
        '''
        if set to true(default), uses training set. if false, uses validation 
        set.
        '''
        self.use_train_set = use_train_set_

ele_data = myData(electron_input_file, validation_fraction)
pho_data = myData(photon_input_file, validation_fraction)
ele_data.useTrainSet(True)
pho_data.useTrainSet(True)
train_data = ConcatDataset((ele_data, pho_data))
trainloader = DataLoader(train_data, batch_size=100, shuffle=True, 
                         num_workers=10)

ele_data.useTrainSet(False)
pho_data.useTrainSet(False)
val_data = ConcatDataset((ele_data, pho_data))
valloader = DataLoader(val_data, batch_size=100, shuffle=False, num_workers=10)

### Prepare Classifier ###
print("Initializing Classifier...")

class Flatten(nn.Module):
    def forward(self, x):
        return x.view(x.size()[0], -1)

net = nn.Sequential(
    nn.Conv2d( 1, 16, 3),
    nn.ReLU(),
    nn.Conv2d(16, 16, 3),
    nn.ReLU(),
    nn.MaxPool2d(2),
    nn.Conv2d(16, 32, 3),
    nn.ReLU(),
    nn.Conv2d(32, 32, 3),
    nn.ReLU(),
    nn.MaxPool2d(2),
    Flatten(),
    nn.Linear(800, 256),
    nn.ReLU(),
    nn.Linear(256, 128),
    nn.ReLU(),
    nn.Linear(128, 2),
)


### Train Classifier ###
net.cuda()
criterion = nn.BCEWithLogitsLoss()
optimizer = optim.Adam(net.parameters())
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=2,
                                                 verbose=True, min_lr=1e-6,
                                                 threshold=1e-3, factor=0.2)

net.eval()
ele_data.useTrainSet(False)
pho_data.useTrainSet(False)
loss = 0.
pred, value = np.array([]), np.array([])

with torch.no_grad():
    for data in valloader:
        inputs, labels, pt = data
        inputs, labels = inputs.cuda(), labels.cuda()
        outputs = net(inputs)

        loss += criterion(outputs, labels).item()
        outputs = F.sigmoid(outputs)
        value = np.concatenate((value, labels[:,1].cpu().numpy()))
        pred = np.concatenate((pred, outputs[:,1].cpu().numpy()))

loss /= len(valloader)
correct, total = 0, 0
correct = (np.around(pred) == value).sum()
total = len(value)
acc = correct/total
auc = roc_auc_score(value, pred)

print("Epoch: %2d" % (0))
print("loss:  %.5f" % (loss))
print("acc:   %.5f" % (acc))
print("auc:   %.5f" % (auc))
print(pred[:6])
print(pred[-6:])
print()

ptdist = np.array([])

for epoch in range(num_epochs):

    net.train()
    ele_data.useTrainSet(True)
    pho_data.useTrainSet(True)
    for data in trainloader:
        inputs, labels, pt = data
        inputs, labels = inputs.cuda(), labels.cuda()
        optimizer.zero_grad()
        outputs = net(inputs)
        loss = criterion(outputs, labels).cuda()
        loss.backward()
        optimizer.step()
    scheduler.step(loss)

    net.eval()
    ele_data.useTrainSet(False)
    pho_data.useTrainSet(False)
    loss = 0.
    pred, value = np.array([]), np.array([])
    
    with torch.no_grad():
        for data in valloader:
            inputs, labels, pt = data
            inputs, labels = inputs.cuda(), labels.cuda()
            outputs = net(inputs)
            
            loss += criterion(outputs, labels).item()
            outputs = F.sigmoid(outputs)
            value = np.concatenate((value, labels[:,1].cpu().numpy()))
            pred = np.concatenate((pred, outputs[:,1].cpu().numpy()))
            if epoch + 1 == num_epochs:
                ptdist = np.concatenate((ptdist, pt.numpy()))

    loss /= len(valloader)
    correct, total = 0, 0
    correct = (np.around(pred) == value).sum()
    total = len(value)
    acc = correct/total
    auc = roc_auc_score(value, pred)
    
    print("Epoch: %2d" % (epoch + 1))
    print("loss:  %.5f" % (loss))
    print("acc:   %.5f" % (acc))
    print("auc:   %.5f" % (auc))
    print(pred[:6])
    print(pred[-6:])
    print()

### Create Plots ###
print("Generating Plots (Performing convoluted for loops)")
ele_pt = np.array([])
ele_pred = np.array([])
pho_pt = np.array([])
pho_pred = np.array([])

for i, label in enumerate(value):
    if label == 0:
        ele_pt = np.append(ele_pt, ptdist[i])
        ele_pred = np.append(ele_pred, pred[i])
    elif label == 1:
        pho_pt = np.append(pho_pt, ptdist[i])
        pho_pred = np.append(pho_pred, pred[i])

auc_bin_size = 20
auc_bins = np.arange(20,160,auc_bin_size)
aucs = np.array([])
for interval in auc_bins:
    int_true = np.array([])
    int_pred = np.array([])
    for i, pt_ in enumerate(ptdist):
        if pt_ > interval and pt_ < interval + auc_bin_size:
            int_true = np.append(int_true, value[i])
            int_pred = np.append(int_pred, pred[i])
    aucs = np.append(aucs, roc_auc_score(int_true, int_pred))

print("Plotting")
plt.figure(figsize=(10,10))

plt.subplot(221)
plt.hist2d(ele_pt, ele_pred, bins=20, range=((20,160),(0,1)))
plt.xlabel("pt")
plt.ylabel("classifier output")
plt.title("Electrons")

plt.subplot(222)
plt.hist2d(pho_pt, pho_pred, bins=20, range=((20,160),(0,1)))
plt.xlabel("pt")
plt.ylabel("classifier output")
plt.title("Photons")

plt.subplot(223)
plt.plot(auc_bins + 10, aucs)
plt.xlabel("pt")
plt.ylabel("roc auc")
plt.title("roc auc over pt (10 GeV intervals)")

plt.tight_layout()
plt.show()

